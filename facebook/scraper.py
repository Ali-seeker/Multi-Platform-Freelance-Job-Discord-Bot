"""
facebook/scraper.py — High-speed HTTP scraper for Facebook notification feed.
Uses curl_cffi with session cookies (c_user + xs) to fetch and parse group notifications
headlessly from Facebook's official Relay notification store without launching any browser.
"""

import json
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

NOTIFICATIONS_URL = "https://www.facebook.com/notifications"


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

        # 1. Check individual variables first as baseline
        if FB_C_USER:
            cookies_dict["c_user"] = FB_C_USER
        if FB_XS:
            cookies_dict["xs"] = FB_XS

        for optional_var in ["FB_DATR", "FB_SB", "FB_I_USER"]:
            val = os.getenv(optional_var, "").strip()
            if val:
                cookie_name = optional_var.replace("FB_", "").lower()
                cookies_dict[cookie_name] = val

        # 2. Raw cookie string (from browser copy) takes highest precedence
        if FB_COOKIES:
            for item in FB_COOKIES.split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    cookies_dict[k.strip()] = v.strip()

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

        # Refresh cookies if updated in environment
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

        # Verify authentication
        is_logged_in = (
            bool(FB_C_USER and FB_C_USER in html_text)
            or "c_user" in resp.cookies
            or "notifications_page" in html_text
        )

        if not is_logged_in and ("login.php" in resp.url or "login_form" in html_text):
            logger.warning(
                "[FACEBOOK] ⚠️ Facebook session appears expired or logged out. Please check your FB_C_USER and FB_XS in .env."
            )
            return []

        return self._extract_notifications_from_page(html_text)

    def _extract_notifications_from_page(self, html: str) -> list[dict]:
        """
        Extracts notification edges from Facebook's preloaded Relay store scripts.
        """
        posts = []
        seen_ids = set()

        # Find JSON script blocks
        scripts = re.findall(
            r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )

        for sc in scripts:
            if "notifications_page" not in sc:
                continue

            try:
                data = json.loads(sc)
            except Exception:
                continue

            # Recursively find notifications_page edges
            edges = self._find_notification_edges(data)
            for edge in edges:
                node = edge.get("node", {})
                notif = node.get("notif", {})
                if not notif:
                    continue

                body_text = notif.get("body", {}).get("text", "").strip()
                raw_url = notif.get("url", "").strip()
                notif_id = str(notif.get("notif_id") or notif.get("id") or "").strip()
                creation_ts = notif.get("creation_time", {}).get("timestamp")

                if not body_text or not notif_id or notif_id in seen_ids:
                    continue

                # Filter for group posts or new post activity
                is_group_post = any(
                    kw in body_text.lower()
                    for kw in [
                        "now in",
                        "has a new post",
                        "has new posts",
                        "posted in",
                        "shared a post in",
                        "added a new post",
                        "new post in",
                        "new post",
                        "in all pakistan jobs",
                    ]
                ) or ("groups" in raw_url and ("posts" in raw_url or "permalink" in raw_url))

                if not is_group_post:
                    continue

                seen_ids.add(notif_id)

                # Clean the URL
                clean_url = self._clean_url(raw_url)
                if not clean_url:
                    clean_url = f"https://www.facebook.com/notifications/?notif_id={notif_id}"

                # Parse author and group name
                author, group_name = self._extract_author_and_group(body_text)

                # Check group filter (if configured)
                if TRACKED_GROUPS:
                    group_lower = group_name.lower()
                    if not any(tg.lower() in group_lower for tg in TRACKED_GROUPS):
                        continue

                # Parse timestamp
                posted_iso = ""
                if creation_ts:
                    try:
                        posted_iso = datetime.fromtimestamp(int(creation_ts), tz=timezone.utc).isoformat()
                    except Exception:
                        posted_iso = datetime.now(timezone.utc).isoformat()
                else:
                    posted_iso = datetime.now(timezone.utc).isoformat()

                # Check matched keyword
                matched_query = "All Posts"
                text_lower = body_text.lower()
                for tq in TRACKED_QUERIES:
                    q = tq.get("query", "all")
                    lbl = tq.get("label", q)
                    if q == "all" or q.lower() in text_lower:
                        matched_query = lbl
                        break

                post_record = {
                    "job_id": notif_id,
                    "title": body_text,
                    "description": (
                        f"**👥 Group:** {group_name}\n"
                        f"**👤 Author:** {author}\n\n"
                        f"**{body_text}**\n\n"
                        f"Click the link below to view or reply to the full post on Facebook."
                    ),
                    "url": clean_url,
                    "budget": "Not specified",
                    "skills": matched_query,
                    "posted_time": posted_iso,
                    "author": author,
                    "group_name": group_name,
                    "query_label": matched_query,
                }
                posts.append(post_record)

        return posts

    def _find_notification_edges(self, obj) -> list[dict]:
        """Traverses JSON structure to extract edges from notifications_page."""
        edges = []
        if isinstance(obj, dict):
            if "notifications_page" in obj:
                page = obj["notifications_page"]
                if isinstance(page, dict) and "edges" in page:
                    edges.extend(page.get("edges", []))
            for v in obj.values():
                edges.extend(self._find_notification_edges(v))
        elif isinstance(obj, list):
            for item in obj:
                edges.extend(self._find_notification_edges(item))
        return edges

    def _clean_url(self, raw_url: str) -> str:
        """Extracts direct canonical Facebook URL from notification link."""
        if not raw_url:
            return ""

        unquoted = urllib.parse.unquote(raw_url)

        # Pattern 1: groups/<id>/posts/<id>
        m = re.search(r"groups/([^/?#&]+)/posts/([^/?#&]+)", unquoted, re.IGNORECASE)
        if m:
            return f"https://www.facebook.com/groups/{m.group(1)}/posts/{m.group(2)}/"

        # Pattern 2: groups/<id>/permalink/<id>
        m2 = re.search(r"groups/([^/?#&]+)/permalink/([^/?#&]+)", unquoted, re.IGNORECASE)
        if m2:
            return f"https://www.facebook.com/groups/{m2.group(1)}/permalink/{m2.group(2)}/"

        # Strip notification tracking parameters
        parsed = urllib.parse.urlparse(raw_url)
        clean = f"https://www.facebook.com{parsed.path}"
        return clean if parsed.path and parsed.path != "/" else raw_url

    def _extract_author_and_group(self, text: str) -> tuple[str, str]:
        """Parses group name and author from notification text."""
        # Pattern 1: [Group Name] has a new post.
        m1 = re.search(
            r"^(.+?)\s+(?:has\s+(?:a|\d+)\s+new\s+posts?|added\s+a\s+new\s+post)",
            text,
            re.IGNORECASE,
        )
        if m1:
            return "Group Member", m1.group(1).strip()

        # Pattern 2: [Author] posted in [Group Name]
        m2 = re.search(
            r"^(.+?)\s+(?:posted|shared a post)\s+in\s+([^:\"]+)",
            text,
            re.IGNORECASE,
        )
        if m2:
            return m2.group(1).strip(), m2.group(2).strip()

        # Pattern 3: New post in [Group Name] by [Author]
        m3 = re.search(r"new post in\s+(.+?)\s+by\s+(.+)", text, re.IGNORECASE)
        if m3:
            return m3.group(2).strip(), m3.group(1).strip()

        # Pattern 4: Now in [Group Name]: "[Snippet]"
        m4 = re.search(r"^Now in\s+([^:\"]+):", text, re.IGNORECASE)
        if m4:
            return "Group Member", m4.group(1).strip()

        return "Facebook Member", "Facebook Group"
