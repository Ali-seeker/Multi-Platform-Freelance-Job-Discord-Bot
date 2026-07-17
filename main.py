"""
main.py — Entry point for the Upwork Job Scraper (Phase 1).

Workflow:
  1. Initialize the SQLite database (creates table if first run)
  2. Create an UpworkScraper instance (sets up session with auth from .env)
  3. Fetch jobs for the configured search query
  4. Loop through results, saving new jobs to the database
  5. Print a summary of what happened

Future phases will add:
  - Discord webhook posting for new jobs
  - Auth token refresh when cookies expire
  - Multiple search queries / URL support
  - Scheduled polling (run every N minutes)
"""

import sys
import io

# Fix Windows console encoding — forces UTF-8 output so emoji/special chars
# don't crash with 'charmap' codec errors on cp1252 terminals.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import SEARCH_QUERY
from scraper import UpworkScraper
from db import init_db, save_job, get_job_count


def main():
    print("=" * 60)
    print("  Upwork Job Scraper -- Phase 1")
    print("=" * 60)
    print()

    # Step 1: Initialize the database (creates jobs table if it doesn't exist)
    init_db()
    jobs_before = get_job_count()
    print(f"[DB] Database initialized -- {jobs_before} existing jobs in database")
    print()

    # Step 2: Create the scraper (loads auth from .env via config.py)
    scraper = UpworkScraper()

    # Step 3: Fetch jobs
    print(f'[SEARCH] Searching for: "{SEARCH_QUERY}"')
    jobs = scraper.fetch_jobs(SEARCH_QUERY)

    if not jobs:
        print("\n[!] No jobs to process. Check the errors above.")
        return

    # Step 4: Save each job, tracking how many are new
    new_count = 0
    for job in jobs:
        was_new = save_job(job)
        if was_new:
            new_count += 1
            print(f"  [NEW] {job['title'][:60]}")
            print(f"        Budget: {job['budget']}  |  Skills: {job['skills'][:50]}")
        else:
            print(f"  [SKIP] (already saved): {job['title'][:60]}")

    # Step 5: Print summary
    print()
    print("-" * 60)
    print(f"[SUMMARY] Fetched {len(jobs)} jobs, "
          f"{new_count} were new and saved to database")
    print(f"          Total jobs in database: {get_job_count()}")
    print("-" * 60)


if __name__ == "__main__":
    main()
