"""
test_workana_sync.py — Interactive diagnosis and dry-run tool for Workana (workana.com) scraping.
Verifies network connectivity, JSON endpoint parsing, project normalization, auto-translation, and Discord formatting.
"""

import sys
import io

# Windows encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from workana.scraper import WorkanaScraper
from workana.formatter import format_workana_job_message, format_workana_thread_details
from workana.config import TRACKED_QUERIES
from utils.translator import translate_job_to_english

print("=" * 60)
print("🔍 WORKANA (workana.com) DIAGNOSTIC & DRY-RUN TOOL")
print("=" * 60)

scraper = WorkanaScraper()

test_query = TRACKED_QUERIES[0]["query"] if TRACKED_QUERIES else "Python"
print(f"\n[Step 1/3] Testing Workana search for query: '{test_query}'...")

try:
    posts = scraper.fetch_jobs(test_query, limit=5)
except Exception as e:
    print(f"❌ Exception fetching from Workana: {e}")
    sys.exit(1)

print(f"  • Successfully extracted {len(posts)} project(s) from Workana.\n")

if not posts:
    print("⚠️ No projects were returned for this query. Trying fallback search 'web'...")
    posts = scraper.fetch_jobs("web", limit=5)

print("[Step 2/3] Sample Extracted & Translated Projects:")
print("-" * 60)
for idx, p in enumerate(posts, 1):
    # Test auto-translation
    p = translate_job_to_english(p)
    
    print(f"{idx}. Project ID: {p.get('job_id')}")
    print(f"   Client:     {p.get('client_name')} ({p.get('client_country')})")
    print(f"   Title:      {p.get('title')}")
    print(f"   Budget:     {p.get('budget')}")
    print(f"   Proposals:  {p.get('proposals_count')}")
    print(f"   URL:        {p.get('url')}")
    print(f"   Time:       {p.get('posted_time')}")
    if p.get("is_translated"):
        print(f"   Language:   🌐 Translated from {p.get('original_language')} to English")
    desc_preview = p.get('description', '')[:120].replace('\n', ' ')
    print(f"   Preview:    {desc_preview}...")
    print("-" * 60)

if posts:
    print("\n[Step 3/3] Simulating Discord Embed & Thread Format for Project 1:")
    sample = translate_job_to_english(posts[0])
    content, embed = format_workana_job_message(sample, query_label=test_query)
    thread_text = format_workana_thread_details(sample)
    print("  • Embed Title:       ", embed.title)
    print("  • Embed URL:         ", embed.url)
    print("  • Embed Description: ", embed.description[:100] + "...")
    print("  • Embed Fields:")
    for f in embed.fields:
        print(f"      - {f.name}: {f.value}")
    print("  • Thread Preview (first 250 chars):")
    print("    " + thread_text[:250].replace("\n", "\n    "))
    print("\n🎉 Success! Workana scraping, translation, and formatting are working flawlessly.")
else:
    print("❌ No projects could be retrieved from Workana.")
