"""
db.py — SQLite database module for multi-platform freelancing job alerts.

Each platform has its own dedicated table in the database (e.g. upwork_jobs, guru_jobs, etc.).
Uses Python's built-in sqlite3.

Schema Design:
──────────────
• job_id (TEXT) — Platform's unique job ID.
• url_source (TEXT) — Search query or URL the job was found under.
• title (TEXT NOT NULL) — Job title.
• description (TEXT) — Full job description.
• budget (TEXT) — Budget or rate string.
• skills (TEXT) — Comma-separated skill names.
• posted_time (TEXT) — When the job was posted (ISO 8601 or raw string).
• fetched_at (TIMESTAMP) — When we scraped it (UTC).
• content_hash (TEXT) — sha256 hash of title|description|budget to detect updates.
• PRIMARY KEY (job_id, url_source)
"""

import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from logger import get_logger

logger = get_logger(__name__)

# Database file lives in the project root
DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")


def _get_connection() -> sqlite3.Connection:
    """Create a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_platform_table(platform: str = "upwork") -> str:
    """Sanitizes platform name and returns the table name (e.g., 'upwork_jobs')."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "", platform.strip().lower())
    return f"{clean}_jobs" if clean else "upwork_jobs"


def init_db(platform: str = "upwork") -> None:
    """
    Initializes the database table for a specific platform.
    Also handles backward-compatible migration from legacy 'jobs' table to 'upwork_jobs'.
    """
    table_name = get_platform_table(platform)
    conn = _get_connection()
    try:
        # Create platform table if it doesn't exist
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                job_id       TEXT,
                url_source   TEXT,
                title        TEXT NOT NULL,
                description  TEXT,
                budget       TEXT,
                skills       TEXT,
                posted_time  TEXT,
                fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                content_hash TEXT DEFAULT '',
                PRIMARY KEY (job_id, url_source)
            )
        """)

        # Check existing columns in the table (for column migrations)
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = [row["name"] for row in cursor.fetchall()]
        if columns and "content_hash" not in columns:
            try:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN content_hash TEXT DEFAULT ''")
                logger.info(f"Added content_hash column to {table_name}.")
            except Exception as e:
                logger.error(f"Migration error for {table_name} content_hash: {e}")

        # Migration from legacy 'jobs' table to 'upwork_jobs'
        if platform.lower() == "upwork":
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
            has_legacy_jobs = cur.fetchone() is not None
            if has_legacy_jobs:
                # Migrate records from legacy 'jobs' to 'upwork_jobs'
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO upwork_jobs (job_id, url_source, title, description, budget, skills, posted_time, fetched_at, content_hash)
                        SELECT job_id, url_source, title, description, budget, skills, posted_time, fetched_at, 
                               COALESCE(content_hash, '')
                        FROM jobs
                    """)
                    logger.info("📦 Migrated existing records from legacy 'jobs' table to 'upwork_jobs'.")
                except Exception as e:
                    logger.warning(f"Note during legacy migration: {e}")

        conn.commit()
    finally:
        conn.close()


def save_job(job_dict: dict, url_source: str, content_hash: str = "", platform: str = "upwork") -> bool:
    """
    Insert or replace a job into the platform's database table.
    """
    table_name = get_platform_table(platform)
    conn = _get_connection()
    try:
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {table_name} (
                job_id, url_source, title, description, budget, skills, posted_time, fetched_at, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(job_dict.get("job_id", "")),
                url_source,
                job_dict.get("title", "Untitled"),
                job_dict.get("description", ""),
                job_dict.get("budget", ""),
                job_dict.get("skills", ""),
                job_dict.get("posted_time", ""),
                datetime.now(timezone.utc).isoformat(),
                content_hash,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def job_exists(job_id: str, url_source: str, platform: str = "upwork") -> bool:
    """
    Check if a job with this ID and URL source is already in the platform table.
    """
    table_name = get_platform_table(platform)
    conn = _get_connection()
    try:
        row = conn.execute(
            f"SELECT 1 FROM {table_name} WHERE job_id = ? AND url_source = ?",
            (str(job_id), url_source),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_job_hash(job_id: str, url_source: str, platform: str = "upwork") -> str | None:
    """
    Returns the content_hash of the job if it exists, otherwise None.
    If the job exists but has no hash (legacy data), returns an empty string.
    """
    table_name = get_platform_table(platform)
    conn = _get_connection()
    try:
        row = conn.execute(
            f"SELECT content_hash FROM {table_name} WHERE job_id = ? AND url_source = ?",
            (str(job_id), url_source),
        ).fetchone()
        if row:
            return row["content_hash"] if row["content_hash"] is not None else ""
        return None
    finally:
        conn.close()


def get_job_count(platform: str = "upwork") -> int:
    """Return the total number of jobs stored for a given platform."""
    table_name = get_platform_table(platform)
    conn = _get_connection()
    try:
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()
        return row["cnt"] if row else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def cleanup_old_jobs(days: int = 14, platform: str = "upwork") -> int:
    """
    Remove jobs from the platform's table that were fetched more than `days` ago.
    Returns the number of rows deleted.
    """
    table_name = get_platform_table(platform)
    conn = _get_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = conn.execute(f"DELETE FROM {table_name} WHERE fetched_at < ?", (cutoff,))
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} jobs older than {days} days from {table_name}.")
        return deleted
    finally:
        conn.close()


def get_all_job_counts() -> dict[str, int]:
    """Return a dictionary of job counts across all platform tables."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_jobs'"
        )
        tables = [row["name"] for row in cursor.fetchall()]
        counts = {}
        for tbl in tables:
            platform = tbl[:-5]  # strip '_jobs'
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {tbl}").fetchone()
            counts[platform] = row["cnt"] if row else 0
        return counts
    finally:
        conn.close()


def init_all_platform_dbs(platforms: list[str] | None = None) -> None:
    """Initializes tables for a list of platforms (defaults to ['upwork'])."""
    if platforms is None:
        platforms = ["upwork"]
    for p in platforms:
        init_db(p)
