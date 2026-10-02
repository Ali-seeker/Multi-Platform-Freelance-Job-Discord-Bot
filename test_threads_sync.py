"""
test_threads_sync.py — Interactive diagnosis and dry-run tool for Threads (threads.net) scraping.
Verifies network connectivity, query execution, Relay JSON parsing, and post extraction.
"""

import sys
import io

# Windows encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from threads.scraper import ThreadsScraper
from threads.formatter import format_threads_job_message, format_threads_thread_details
from threads.config import TRACKED_QUERIES

print("=" * 60)
print("🔍 THREADS (threads.net) DIAGNOSTIC & DRY-RUN TOOL")
print("=" * 60)

scraper = ThreadsScraper()

test_query = TRACKED_QUERIES[0]["query"] if TRACKED_QUERIES else "hiring developer"
print(f"\n[Step 1/3] Testing Threads search for query: '{test_query}'...")

try:
    posts = scraper.fetch_jobs(test_query, limit=5)
except Exception as e:
    print(f"❌ Exception fetching from Threads: {e}")
    sys.exit(1)

print(f"  • Successfully extracted {len(posts)} recent post(s) from Threads.\n")

if not posts:
    print("⚠️ No posts were returned for this query. Trying fallback search 'hiring'...")
    posts = scraper.fetch_jobs("hiring", limit=5)

print("[Step 2/3] Sample Extracted Posts:")
print("-" * 60)
for idx, p in enumerate(posts, 1):
    print(f"{idx}. Post ID: {p.get('job_id')}")
    print(f"   Author:  {p.get('author')}")
    print(f"   Title:   {p.get('title')}")
    print(f"   URL:     {p.get('url')}")
    print(f"   Time:    {p.get('posted_time')}")
    desc_preview = p.get('description', '')[:120].replace('\n', ' ')
    print(f"   Preview: {desc_preview}...")
    print("-" * 60)

if posts:
    print("\n[Step 3/3] Simulating Discord Thread Format for Post 1:")
    sample = posts[0]
    content, embed = format_threads_job_message(sample, query_label=test_query)
    thread_text = format_threads_thread_details(sample)
    print("  • Embed Title:      ", embed.title)
    print("  • Embed URL:        ", embed.url)
    print("  • Embed Description:", embed.description)
    print("  • Thread Preview (first 200 chars):")
    print("    " + thread_text[:200].replace("\n", "\n    "))
    print("\n🎉 Success! Threads scraping and formatting are working flawlessly.")
else:
    print("❌ No posts extracted.")
