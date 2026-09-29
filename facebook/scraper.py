"""
facebook/scraper.py — High-speed HTTP scraper for Facebook notification feed.
Uses curl_cffi with session cookies (c_user + xs) to fetch and parse group notifications
headlessly without launching any browser.
"""

import os
import re
import urllib.parse
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from curl_cffi import requests

from facebook.config import (
    FB_C_USER,
    FB_XS,
    FB_COOKIES,
    TRACKED_QUERIES,
    TRACKED_GROUPS,
)
from logger import get_logger

logger = get_logger(__name__)

NOTIFICATIONS_URL = "https://mbasic.facebook.com/notifications.php"
DESKTOP_NOTIF_URL = "https://www.facebook.com/notifications"


class FacebookNotificationScraper:
    """
    Direct HTTP scraper that checks the user's Facebook notification feed
    using authenticated session cookies (c_user & xs).
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self._init_cookies()

    def _init_cookies(self):
        """Builds and loads cookie jar for the session."""
        cookies_dict = {}

        # 1. Check if raw cookie string is provided
        if FB_COOKIES:
            for item in FB_COOKIES.split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    cookies_dict[k.strip()] = v.strip()

        # 2. Check individual c_user and xs variables
        if FB_C_USER:
            cookies_dict["c_user"] = FB_C_USER
        if FB_XS:
            cookies_dict["xs"] = FB_XS

        for k, v in cookies_dict.items():
            self.session.cookies.set(k, v, domain=".facebook.com")

    def is_configured(self) -> bool:
        """Returns True if essential Facebook cookies (c_user and xs) are set."""
        cookie_keys = list(self.session.cookies.keys())
        has_c_user = "c_user" in cookie_keys or bool(FB_C_USER)
        has_xs = "xs" in cookie_keys or bool(FB_XS)
        return has_c_user and has_xs

    def fetch_notifications(self) -> list[dict]:
        """
        Fetches the notifications page from Facebook and parses group post alerts.
        Returns a list of standardized job dictionaries.
        """
        if not self.is_configured():
            logger.warning(
                "[FACEBOOK] ⚠️ Facebook cookies (c_user and xs) are not set in .env! "
                "Please add FB_C_USER and FB_XS to your .env file."
            )
            return []

        # Refresh cookies if updated
        self._init_cookies()

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            resp = self.session.get(
                NOTIFICATIONS_URL,
                headers=headers,
                timeout=15,
                allow_redirects=True,
            )
        except Exception as e:
            logger.error(f"[FACEBOOK] Network error requesting notifications: {e}")
            return []

        if resp.status_code != 200:
            logger.warning(f"[FACEBOOK] HTTP {resp.status_code} while fetching notifications.")
            return []

        html_text = resp.text

        # Detect login wall or expired session
        if "login_form" in html_text or "checkpoint" in html_text or "mbasic_logout_button" not in html_text:
            if "login.php" in resp.url or "c_user" not in html_text:
                logger.warning(
                    "[FACEBOOK] ⚠️ Facebook session appears expired or logged out. Please check your FB_C_USER and FB_XS in .env."
                )

        return self._parse_notifications_html(html_text)

    def _parse_notifications_html(self, html: str) -> list[dict]:
        """
        Parses notification items from mbasic.facebook.com/notifications.php.
        """
        soup = BeautifulSoup(html, "html.parser")
        posts = []

        # Find notification links and containers
        # In mbasic, notifications are usually within <table> or <div> containing links with href containing group links or redirect links
        notif_elements = soup.find_all("a", href=True)

        seen_links = set()

        for a_tag in notif_elements:
            href = a_tag["href"]
            raw_text = a_tag.get_text(strip=True)

            if not raw_text or len(raw_text) < 5:
                continue

            # Check if this link points to a group or post notification
            is_group_notif = any(
                kw in raw_text.lower()
                for kw in [
                    "has a new post",
                    "has new posts",
                    "posted in",
                    "shared a post in",
                    "added a post in",
                    "new post",
                ]
            ) or ("groups" in href and ("posts" in href or "permalink" in href or "notif_t" in href))

            if not is_group_notif:
                continue

            # Resolve canonical post URL
            full_url = urllib.parse.urljoin("https://www.facebook.com", href)

            # Unpack tracking redirects (e.g. /n/?groups... or /a/notifications.php?...)
            clean_url = self._clean_url(full_url)

            if clean_url in seen_links:
                continue
            seen_links.add(clean_url)

            # Parse Author and Group Name
            author, group_name = self._extract_author_and_group(raw_text)

            # Check group filter (if configured)
            if TRACKED_GROUPS:
                group_lower = group_name.lower()
                if not any(tg.lower() in group_lower for tg in TRACKED_GROUPS):
                    continue

            # Extract unique post ID
            post_id = self._extract_post_id(clean_url, raw_text)

            # Tag matched query
            matched_query = "All Posts"
            text_lower = raw_text.lower()
            for tq in TRACKED_QUERIES:
                q = tq.get("query", "all")
                lbl = tq.get("label", q)
                if q == "all" or q.lower() in text_lower:
                    matched_query = lbl
                    break

            post_record = {
                "job_id": post_id,
                "title": raw_text,
                "description": f"New activity from {author} in Facebook Group: {group_name}.\n\nClick the link below to view or reply to the full post on Facebook.",
                "url": clean_url,
                "budget": "Not specified",
                "skills": matched_query,
                "posted_time": datetime.now(timezone.utc).isoformat(),
                "author": author,
                "group_name": group_name,
                "query_label": matched_query,
            }
            posts.append(post_record)

        return posts

    def _clean_url(self, raw_url: str) -> str:
        """Extracts direct canonical Facebook URL from notifications link."""
        unquoted = urllib.parse.unquote(raw_url)

        # Pattern 1: groups/<id>/posts/<id>
        m = re.search(r"groups/([^/?#&]+)/posts/([^/?#&]+)", unquoted, re.IGNORECASE)
        if m:
            return f"https://www.facebook.com/groups/{m.group(1)}/posts/{m.group(2)}/"

        # Pattern 2: groups/<id>/permalink/<id>
        m2 = re.search(r"groups/([^/?#&]+)/permalink/([^/?#&]+)", unquoted, re.IGNORECASE)
        if m2:
            return f"https://www.facebook.com/groups/{m2.group(1)}/permalink/{m2.group(2)}/"

        # Pattern 3: photo/?fbid=<id>
        m3 = re.search(r"photo(?:\.php)?\?[^#]*\bfbid=(\d+)", unquoted, re.IGNORECASE)
        if m3:
            return f"https://www.facebook.com/photo/?fbid={m3.group(1)}"

        # Strip tracking queries
        parsed = urllib.parse.urlparse(raw_url)
        clean = f"https://www.facebook.com{parsed.path}"
        return clean if parsed.path else raw_url

    def _extract_author_and_group(self, text: str) -> tuple[str, str]:
        """Parses group name and author from notification text."""
        # Pattern 1: [Group Name] has a new post.
        m1 = re.search(r"^(.+?)\s+(?:has\s+(?:a|\d+)\s+new\s+posts?|added\s+a\s+new\s+post)", text, re.IGNORECASE)
        if m1:
            return "Group Member", m1.group(1).strip()

        # Pattern 2: [Author] posted in [Group Name]
        m2 = re.search(r"^(.+?)\s+(?:posted|shared a post)\s+in\s+([^:\"]+)", text, re.IGNORECASE)
        if m2:
            return m2.group(1).strip(), m2.group(2).strip()

        # Pattern 3: New post in [Group Name] by [Author]
        m3 = re.search(r"new post in\s+(.+?)\s+by\s+(.+)", text, re.IGNORECASE)
        if m3:
            return m3.group(2).strip(), m3.group(1).strip()

        return "Facebook Member", "Facebook Group"

    def _extract_post_id(self, clean_url: str, text: str) -> str:
        """Extracts unique ID for database deduplication."""
        id_match = re.search(r"/(?:posts|permalink|fbid=)/?(\d+)", clean_url)
        if id_match:
            return id_match.group(1)

        # Fallback to hash of url and text
        return f"fb_{abs(hash(clean_url + text))}"
