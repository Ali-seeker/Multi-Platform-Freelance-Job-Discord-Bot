"""
db.py — SQLite database module for storing scraped Upwork jobs.

Uses Python's built-in sqlite3 (no extra dependencies).

Schema Design Notes:
─────────────────────
• job_id (TEXT PRIMARY KEY) — Upwork's unique job ID (e.g., "2072926869803851328").
  Using TEXT instead of INTEGER because these IDs are very large numbers that
  could exceed SQLite's integer range, and we never do math on them.

• skills (TEXT) — Stored as a comma-separated string (e.g., "Python, Django, React").
  For Phase 1 this is simple and queryable with LIKE. If you later need to
  filter by individual skills, consider a separate job_skills junction table.

• fetched_at (TIMESTAMP) — Automatically set to the current UTC time when the
  row is inserted. Useful for knowing when YOU scraped the job, vs. when it
  was posted on Upwork (posted_time).

Deduplication Strategy:
───────────────────────
We use INSERT OR IGNORE which silently skips the insert if a row with the
same job_id (PRIMARY KEY) already exists. This is simpler and faster than
checking job_exists() before every insert, and it's safe for concurrent use.
We still provide job_exists() for cases where you want to check before
doing other processing (e.g., deciding whether to post to Discord).
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from logger import get_logger

logger = get_logger(__name__)

# Database file lives in the project root
DB_PATH = "jobs.db"


def _get_connection() -> sqlite3.Connection:
    """Create a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    # Return rows as sqlite3.Row objects so we can access columns by name
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    Create the jobs table if it doesn't already exist.
    Also handles migration from the old schema (single primary key)
    to the new schema (composite primary key with url_source).
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("PRAGMA table_info(jobs)")
        columns = [row['name'] for row in cursor.fetchall()]

        if columns and 'url_source' not in columns:
            logger.info("Migrating database to new schema (adding url_source)...")
            conn.execute("ALTER TABLE jobs RENAME TO jobs_old")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT,                -- Upwork's unique job identifier
                url_source  TEXT,                -- The URL/query this job was found under
                title       TEXT NOT NULL,       -- Job title (with H^ markers stripped)
                description TEXT,                -- Full job description
                budget      TEXT,                -- Budget string (e.g., "$800" or "$20-$25/hr")
                skills      TEXT,                -- Comma-separated skill names
                posted_time TEXT,                -- When the job was posted on Upwork (ISO 8601)
                fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- When we scraped it
                PRIMARY KEY (job_id, url_source)
            )
        """)

        if columns and 'url_source' not in columns:
            conn.execute("""
                INSERT INTO jobs (job_id, url_source, title, description, budget, skills, posted_time, fetched_at)
                SELECT job_id, 'legacy', title, description, budget, skills, posted_time, fetched_at
                FROM jobs_old
            """)
            conn.execute("DROP TABLE jobs_old")
            logger.info("Migration complete.")

        conn.commit()
    finally:
        conn.close()


def save_job(job_dict: dict, url_source: str) -> bool:
    """
    Insert a job into the database. Returns True if the job was newly inserted,
    False if it already existed (was skipped) for this specific URL source.
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO jobs (job_id, url_source, title, description, budget, skills, posted_time, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_dict["job_id"],
                url_source,
                job_dict["title"],
                job_dict["description"],
                job_dict.get("budget", ""),
                job_dict.get("skills", ""),
                job_dict.get("posted_time", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        # rowcount is 1 if a new row was inserted, 0 if it was ignored (duplicate)
        return cursor.rowcount == 1
    finally:
        conn.close()


def job_exists(job_id: str, url_source: str) -> bool:
    """
    Check if a job with this ID and URL source is already in the database.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE job_id = ? AND url_source = ?", (job_id, url_source)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_job_count() -> int:
    """Return the total number of jobs in the database."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM jobs").fetchone()
        return row["cnt"]
    finally:
        conn.close()

def cleanup_old_jobs(days: int = 14) -> int:
    """
    Remove jobs from the database that were fetched more than `days` ago.
    Returns the number of rows deleted.
    """
    conn = _get_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = conn.execute("DELETE FROM jobs WHERE fetched_at < ?", (cutoff,))
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} jobs older than {days} days.")
        return deleted
    finally:
        conn.close()
