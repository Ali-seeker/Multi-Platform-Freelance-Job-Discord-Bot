"""
test_offline.py -- Verifies Phase 1 works end-to-end using the sample response
data from the user's original DevTools capture. No network requests needed.

Tests:
  1. parse_job() correctly extracts fields from raw GraphQL JSON
  2. H^...^H highlight markers are stripped from titles/descriptions
  3. Budget formatting works for FIXED and HOURLY jobs
  4. Database init, save, deduplication (INSERT OR IGNORE), and job_exists all work
  5. Running save_job twice with the same data doesn't create duplicates
"""

import os
import sys

# Force UTF-8 for Windows console
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Use a test database instead of the real one
import db
db.DB_PATH = "test_jobs.db"

from scraper import parse_job
from db import init_db, save_job, job_exists, get_job_count

# --- Sample response data (from the user's DevTools capture) ---
SAMPLE_RESULTS = [
    {
        "id": "2072926869803851328",
        "title": "H^Python^H H^Developer^H",
        "description": "Position- H^Python^H H^Developer^H\nExp- 4-6 yrs\nMonthly Budget: $800",
        "ontologySkills": [
            {"uid": "996364628025274386", "prefLabel": "Python", "prettyName": "Python", "highlighted": True}
        ],
        "jobTile": {
            "job": {
                "id": "2072926869803851328",
                "jobType": "FIXED",
                "hourlyBudgetMax": None,
                "hourlyBudgetMin": None,
                "createTime": "2026-07-03T06:14:13.856Z",
                "publishTime": "2026-07-03T06:16:46.524Z",
                "fixedPriceAmount": {"amount": "800.0"},
                "hourlyEngagementDuration": None,
                "fixedPriceEngagementDuration": {"label": "More than 6 months", "weeks": 52},
            }
        },
    },
    {
        "id": "2068723994201831082",
        "title": "Senior H^Python^H H^Developer^H",
        "description": "Looking for candidates with more explicit H^Python^H and SDK experience.",
        "ontologySkills": [
            {"uid": "996364628025274386", "prefLabel": "Python", "prettyName": "Python", "highlighted": True},
            {"uid": "1031626732309299200", "prefLabel": "Django", "prettyName": "Django", "highlighted": False},
            {"uid": "1031626778132070400", "prefLabel": "Scrapy", "prettyName": "Scrapy", "highlighted": False},
        ],
        "jobTile": {
            "job": {
                "id": "2068723994201831082",
                "jobType": "HOURLY",
                "hourlyBudgetMax": "25.0",
                "hourlyBudgetMin": "20.0",
                "createTime": "2026-06-21T15:53:30.288Z",
                "publishTime": "2026-06-21T18:54:24.599Z",
                "fixedPriceAmount": None,
                "hourlyEngagementDuration": {"label": "More than 6 months", "weeks": 52},
                "fixedPriceEngagementDuration": None,
            }
        },
    },
    {
        "id": "2074448721772088029",
        "title": "H^Python^H Full-Stack H^Developer^H",
        "description": "Job Title: H^Python^H Full Stack H^Developer^H",
        "ontologySkills": [
            {"uid": "996364628025274386", "prefLabel": "Python", "prettyName": "Python", "highlighted": True},
            {"uid": "1031626732309299200", "prefLabel": "Django", "prettyName": "Django", "highlighted": False},
            {"uid": "1691099315655159809", "prefLabel": "FastAPI", "prettyName": "FastAPI", "highlighted": False},
        ],
        "jobTile": {
            "job": {
                "id": "2074448721772088029",
                "jobType": "HOURLY",
                "hourlyBudgetMax": None,
                "hourlyBudgetMin": None,
                "createTime": "2026-07-07T11:01:31.688Z",
                "publishTime": "2026-07-07T11:02:52.970Z",
                "fixedPriceAmount": None,
                "hourlyEngagementDuration": {"label": "3 to 6 months", "weeks": 18},
                "fixedPriceEngagementDuration": None,
            }
        },
    },
]


def test_parse_job():
    """Test that parse_job correctly extracts and cleans fields."""
    print("=" * 60)
    print("  TEST 1: parse_job()")
    print("=" * 60)

    # Test fixed-price job
    job1 = parse_job(SAMPLE_RESULTS[0])
    assert job1["job_id"] == "2072926869803851328", f"Bad job_id: {job1['job_id']}"
    assert job1["title"] == "Python Developer", f"H^ markers not stripped from title: {job1['title']}"
    assert "H^" not in job1["description"], f"H^ markers not stripped from description"
    assert job1["budget"] == "$800.0 (Fixed)", f"Bad budget: {job1['budget']}"
    assert job1["skills"] == "Python", f"Bad skills: {job1['skills']}"
    assert job1["posted_time"] == "2026-07-03T06:16:46.524Z", f"Bad posted_time: {job1['posted_time']}"
    print("  [PASS] Fixed-price job parsed correctly")
    print(f"         Title: {job1['title']}")
    print(f"         Budget: {job1['budget']}")
    print(f"         Skills: {job1['skills']}")
    print()

    # Test hourly job with budget range
    job2 = parse_job(SAMPLE_RESULTS[1])
    assert job2["title"] == "Senior Python Developer", f"Bad title: {job2['title']}"
    assert job2["budget"] == "$20.0-$25.0/hr", f"Bad budget: {job2['budget']}"
    assert "Django" in job2["skills"], f"Missing skill Django: {job2['skills']}"
    assert "Scrapy" in job2["skills"], f"Missing skill Scrapy: {job2['skills']}"
    print("  [PASS] Hourly job with budget range parsed correctly")
    print(f"         Title: {job2['title']}")
    print(f"         Budget: {job2['budget']}")
    print(f"         Skills: {job2['skills']}")
    print()

    # Test hourly job with no budget
    job3 = parse_job(SAMPLE_RESULTS[2])
    assert job3["title"] == "Python Full-Stack Developer", f"Bad title: {job3['title']}"
    assert job3["budget"] == "Hourly (budget not listed)", f"Bad budget: {job3['budget']}"
    print("  [PASS] Hourly job with no budget parsed correctly")
    print(f"         Title: {job3['title']}")
    print(f"         Budget: {job3['budget']}")
    print(f"         Skills: {job3['skills']}")
    print()


def test_database():
    """Test database creation, insertion, deduplication, and existence check."""
    print("=" * 60)
    print("  TEST 2: Database Operations")
    print("=" * 60)

    # Clean up any previous test database
    if os.path.exists("test_jobs.db"):
        os.remove("test_jobs.db")

    # Test init
    init_db()
    assert os.path.exists("test_jobs.db"), "Database file not created"
    print("  [PASS] init_db() created test_jobs.db")

    # Test save_job
    job1 = parse_job(SAMPLE_RESULTS[0])
    was_new = save_job(job1)
    assert was_new is True, "First insert should return True (new)"
    print("  [PASS] save_job() returned True for new job")

    # Test job_exists
    assert job_exists("2072926869803851328") is True, "job_exists should return True"
    assert job_exists("9999999999999999999") is False, "job_exists should return False for unknown ID"
    print("  [PASS] job_exists() returns correct True/False")

    # Test deduplication (INSERT OR IGNORE)
    was_new_again = save_job(job1)
    assert was_new_again is False, "Duplicate insert should return False"
    print("  [PASS] save_job() returned False for duplicate (INSERT OR IGNORE works)")

    # Test count
    assert get_job_count() == 1, f"Expected 1 job, got {get_job_count()}"

    # Save remaining jobs
    for raw in SAMPLE_RESULTS[1:]:
        job = parse_job(raw)
        save_job(job)

    assert get_job_count() == 3, f"Expected 3 jobs, got {get_job_count()}"
    print(f"  [PASS] Saved {get_job_count()} unique jobs to database")

    # Run save_job on ALL again to verify no duplicates are created
    for raw in SAMPLE_RESULTS:
        job = parse_job(raw)
        was_new = save_job(job)
        assert was_new is False, f"Duplicate job {job['job_id']} was inserted again!"
    assert get_job_count() == 3, "Deduplication failed -- count changed after re-insert"
    print("  [PASS] Re-saving all 3 jobs created 0 duplicates (still 3 total)")

    # Cleanup
    os.remove("test_jobs.db")
    print("  [PASS] Test database cleaned up")
    print()


def test_full_workflow():
    """Simulate the main.py workflow with sample data."""
    print("=" * 60)
    print("  TEST 3: Full Workflow Simulation")
    print("=" * 60)

    if os.path.exists("test_jobs.db"):
        os.remove("test_jobs.db")

    init_db()
    print(f"  [DB] Database initialized -- {get_job_count()} existing jobs")

    # Simulate fetch_jobs returning parsed data
    jobs = [parse_job(raw) for raw in SAMPLE_RESULTS]
    print(f"  [OK] Fetched {len(jobs)} jobs (simulated)")

    # First run -- all jobs are new
    new_count = 0
    for job in jobs:
        was_new = save_job(job)
        if was_new:
            new_count += 1
            print(f"    [NEW] {job['title'][:60]}")
            print(f"          Budget: {job['budget']}  |  Skills: {job['skills'][:50]}")
        else:
            print(f"    [SKIP] (already saved): {job['title'][:60]}")

    print()
    print(f"  [SUMMARY] Fetched {len(jobs)} jobs, {new_count} were new and saved to database")
    print(f"            Total jobs in database: {get_job_count()}")
    assert new_count == 3, f"Expected 3 new jobs on first run, got {new_count}"
    print("  [PASS] First run: all 3 jobs saved as new")
    print()

    # Second run -- all jobs are duplicates
    print("  --- Simulating second run (should skip all) ---")
    new_count_2 = 0
    for job in jobs:
        was_new = save_job(job)
        if was_new:
            new_count_2 += 1
            print(f"    [NEW] {job['title'][:60]}")
        else:
            print(f"    [SKIP] (already saved): {job['title'][:60]}")

    print()
    print(f"  [SUMMARY] Fetched {len(jobs)} jobs, {new_count_2} were new and saved to database")
    print(f"            Total jobs in database: {get_job_count()}")
    assert new_count_2 == 0, f"Expected 0 new jobs on second run, got {new_count_2}"
    assert get_job_count() == 3, f"Expected 3 total, got {get_job_count()}"
    print("  [PASS] Second run: all 3 jobs correctly skipped (deduplication works)")

    # Cleanup
    os.remove("test_jobs.db")
    print()


if __name__ == "__main__":
    print()
    print("*" * 60)
    print("  OFFLINE TEST SUITE -- Phase 1 Verification")
    print("*" * 60)
    print()

    try:
        test_parse_job()
        test_database()
        test_full_workflow()

        print("=" * 60)
        print("  ALL TESTS PASSED!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n  [FAIL] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  [ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
