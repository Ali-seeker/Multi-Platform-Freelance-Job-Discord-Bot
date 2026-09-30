"""
test_facebook_sync.py — Interactive diagnosis and dry-run tool for Facebook notification scraping.
Verifies your cookies, tests notification fetching, and checks Discord channel delivery.
"""

import sys
import io
import os
from datetime import datetime

# Windows encoding fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(override=True)

from facebook.scraper import FacebookNotificationScraper
from facebook.formatter import format_facebook_job_message
from facebook.config import FB_C_USER, FB_XS, FB_COOKIES, CHANNEL_ID
from db import init_db, get_job_count

print("=" * 60)
print("🔍 FACEBOOK BOT DIAGNOSTIC & DRY RUN TOOL")
print("=" * 60)

# Step 1: Check Environment Configuration
print("\n[Step 1/3] Checking .env configuration...")
has_cookies = bool(FB_COOKIES)
has_c_user = bool(FB_C_USER)
has_xs = bool(FB_XS)

print(f"  • FB_C_USER: {'✅ Present (' + FB_C_USER + ')' if has_c_user else '❌ Missing'}")
print(f"  • FB_XS:     {'✅ Present (' + FB_XS[:15] + '...)' if has_xs else '❌ Missing'}")
print(f"  • FB_COOKIES:{'✅ Present (' + str(len(FB_COOKIES)) + ' chars)' if has_cookies else '⚪ Not set (using individual c_user & xs)'}")

if not has_cookies and not (has_c_user and has_xs):
    print("\n❌ Error: Neither FB_COOKIES nor (FB_C_USER + FB_XS) are configured in .env.")
    print("Please follow the instructions to set your cookies.")
    sys.exit(1)

# Step 2: Test Live Fetch from Facebook
print("\n[Step 2/3] Connecting to Facebook Notifications...")
scraper = FacebookNotificationScraper()

try:
    posts = scraper.fetch_notifications()
except Exception as e:
    print(f"❌ Exception connecting to Facebook: {e}")
    sys.exit(1)

print(f"  • Scraped {len(posts)} valid group post notification(s).")

if not posts:
    print("\n⚠️ No group post notifications were returned by Facebook for this session.")
    print("This happens when:")
    print("  1. The cookies in .env are expired or from an older session.")
    print("  2. You have not copied the new cookies since opening Facebook.")
    print("\n👉 Solution: Copy the fresh 'Cookie' header from your browser Network tab into FB_COOKIES in .env.")
    sys.exit(0)

# Step 3: Display Results
print("\n[Step 3/3] Found Group Post Notifications:")
print("-" * 60)
for idx, p in enumerate(posts, 1):
    print(f"{idx}. Group: {p.get('group_name')}")
    print(f"   Title: {p.get('title')}")
    print(f"   URL:   {p.get('url')}")
    print(f"   Time:  {p.get('posted_time')}")
    desc = p.get('description', '')
    desc_preview = desc[:150].replace('\n', ' ')
    print(f"   Description: {desc_preview}...")
    print("-" * 60)

print(f"\n🎉 Success! The bot can read {len(posts)} group post(s) from Facebook.")
print("When you run 'python main.py --platform facebook', these will be posted to Discord #facebook.")
