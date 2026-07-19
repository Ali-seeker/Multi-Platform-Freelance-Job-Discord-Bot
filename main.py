"""
main.py — Entry point for the Upwork Job Scraper (Phase 1 CLI mode).

Workflow:
  1. Initialize the SQLite database (creates table if first run)
  2. Create an UpworkScraper instance (sets up session with auth from .env)
  3. Fetch jobs for the configured search query
  4. Loop through results, saving new jobs to the database
  5. Print a summary of what happened

Note:
  For Phase 2 (Discord Bot mode), run `python discord_bot.py` instead of main.py.
  Make sure to set DISCORD_TOKEN and DISCORD_CHANNEL_ID in your .env file first.
"""

import sys
import io

# Fix Windows console encoding — forces UTF-8 output so emoji/special chars
# don't crash with 'charmap' codec errors on cp1252 terminals.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import urllib.parse
from config import TRACKED_URLS
from scraper import UpworkScraper
from db import init_db, save_job, get_job_count
from logger import get_logger

logger = get_logger(__name__)


def main():
    logger.info("=" * 60)
    logger.info("  Upwork Job Scraper -- Phase 1")
    logger.info("=" * 60)

    # Step 1: Initialize the database (creates jobs table if it doesn't exist)
    init_db()
    jobs_before = get_job_count()
    logger.info(f"Database initialized -- {jobs_before} existing jobs in database")

    # Step 2: Create the scraper (loads auth from .env via config.py)
    scraper = UpworkScraper()

    if not TRACKED_URLS:
        logger.error("No tracked_urls found in config.json")
        return

    url_config = TRACKED_URLS[0]
    url_source = url_config["url"]
    label = url_config["label"]

    parsed_url = urllib.parse.urlparse(url_source)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    search_query = query_params.get('q', [''])[0] or label

    # Step 3: Fetch jobs
    logger.info(f'Searching for: "{search_query}" (from {label})')
    jobs = scraper.fetch_jobs(search_query)

    if not jobs:
        logger.warning("No jobs to process. Check the errors above.")
        return

    # Step 4: Save each job, tracking how many are new
    new_count = 0
    for job in jobs:
        was_new = save_job(job, url_source)
        if was_new:
            new_count += 1
            logger.info(f"  [NEW] {job['title'][:60]}")
            logger.info(f"        Budget: {job['budget']}  |  Skills: {job['skills'][:50]}")
        else:
            logger.info(f"  [SKIP] (already saved): {job['title'][:60]}")

    # Step 5: Print summary
    logger.info("-" * 60)
    logger.info(f"Fetched {len(jobs)} jobs, {new_count} were new and saved to database")
    logger.info(f"Total jobs in database: {get_job_count()}")
    logger.info("-" * 60)


if __name__ == "__main__":
    main()
