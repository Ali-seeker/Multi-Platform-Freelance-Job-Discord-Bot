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
        self._content_cache = {}
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

    def fetch_post_content(self, post_url: str, post_id: str = "") -> str:
        """
        Fetches the target Facebook post page and extracts the full body/message text.
        Falls back to empty string if unavailable or rate limited.
        """
        if not post_url or not self.is_configured():
            return ""

        if post_id and post_id in self._content_cache:
            return self._content_cache[post_id]

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            logger.info(f"[FACEBOOK] 📄 Fetching full post content for post {post_id or 'unknown'} ({post_url})...")
            resp = self.session.get(
                post_url,
                headers=headers,
                timeout=18,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                logger.debug(f"[FACEBOOK] HTTP {resp.status_code} fetching post content for {post_url}")
                return ""

            html = resp.text
            scripts = re.findall(
                r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                html,
                re.DOTALL,
            )

            # Strategy 1: Look in scripts that specifically contain the post ID
            if post_id:
                for sc in scripts:
                    if post_id in sc:
                        msgs = re.findall(r'"message":\{"text":"([^"]+)"\}', sc)
                        for m in msgs:
                            try:
                                dec = json.loads(f'"{m}"')
                            except Exception:
                                dec = m.encode("utf-8").decode("unicode_escape", errors="replace")
                            dec = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", dec).strip()
                            if len(dec) > 10:
                                self._content_cache[post_id] = dec
                                return dec

            # Strategy 2: Look in scripts containing story or message
            for sc in scripts:
                if '"story":' in sc or '"message":' in sc:
                    msgs = re.findall(r'"message":\{"text":"([^"]+)"\}', sc)
                    for m in msgs:
                        try:
                            dec = json.loads(f'"{m}"')
                        except Exception:
                            dec = m.encode("utf-8").decode("unicode_escape", errors="replace")
                        dec = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", dec).strip()
                        if len(dec) > 20:
                            if post_id:
                                self._content_cache[post_id] = dec
                            return dec

        except Exception as e:
            logger.debug(f"[FACEBOOK] Could not fetch post content from {post_url}: {e}")

        return ""

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
                timeout=18,
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
                clean_body = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", body_text).strip()
                raw_url = notif.get("url", "").strip()
                notif_id = str(notif.get("notif_id") or notif.get("id") or "").strip()
                creation_ts = notif.get("creation_time", {}).get("timestamp")

                if not clean_body or not notif_id or notif_id in seen_ids:
                    continue

                # Filter for group posts or new post activity
                is_group_post = any(
                    kw in clean_body.lower()
                    for kw in [
                        "now in",
                        "has a new post",
                        "has new posts",
                        "posted in",
                        "shared a post in",
                        "added a new post",
                        "new post in",
                        "new post",
                    ]
                ) or ("groups" in raw_url and ("posts" in raw_url or "permalink" in raw_url or "multi_permalinks" in raw_url))

                if not is_group_post:
                    continue

                seen_ids.add(notif_id)

                # Clean the URL and extract post ID
                clean_url = self._clean_url(raw_url)
                if not clean_url:
                    clean_url = f"https://www.facebook.com/notifications/?notif_id={notif_id}"

                target_post_id = self._extract_post_id(raw_url) or self._extract_post_id(clean_url)

                # Parse author and group name
                author, group_name = self._extract_author_and_group(body_text)

                # Check group filter (if configured)
                if TRACKED_GROUPS:
                    group_lower = group_name.lower()
                    if not any(tg.lower() in group_lower for tg in TRACKED_GROUPS):
                        continue

                # Fetch full post content from Facebook post page
                full_content = ""
                if clean_url and "posts" in clean_url:
                    full_content = self.fetch_post_content(clean_url, target_post_id)

                # Parse timestamp
                posted_iso = ""
                if creation_ts:
                    try:
                        posted_iso = datetime.fromtimestamp(int(creation_ts), tz=timezone.utc).isoformat()
                    except Exception:
                        posted_iso = datetime.now(timezone.utc).isoformat()
                else:
                    posted_iso = datetime.now(timezone.utc).isoformat()

                # Check matched keyword across notification and full content
                matched_query = "All Posts"
                text_to_match = f"{clean_body} {full_content}".lower()
                for tq in TRACKED_QUERIES:
                    q = tq.get("query", "all")
                    lbl = tq.get("label", q)
                    if q == "all" or q.lower() in text_to_match:
                        matched_query = lbl
                        break

                # Determine post description
                if full_content:
                    final_description = full_content
                else:
                    final_description = (
                        f"**👥 Group:** {group_name}\n"
                        f"**👤 Author:** {author}\n\n"
                        f"**{clean_body}**\n\n"
                        f"Click the link below to view or reply to the full post on Facebook."
                    )

                # Determine clean title: prefer first informative line of full content
                post_title = clean_body
                if full_content:
                    for line in full_content.splitlines():
                        candidate = line.strip()
                        if 10 <= len(candidate) <= 120 and not candidate.startswith("http"):
                            post_title = candidate
                            break

                post_record = {
                    "job_id": notif_id,
                    "post_id": target_post_id,
                    "title": post_title,
                    "description": final_description,
                    "url": clean_url,
                    "budget": "Not specified",
                    "skills": matched_query,
                    "posted_time": posted_iso,
                    "author": author,
                    "group_name": group_name,
                    "query_label": matched_query,
                    "notif_body": clean_body,
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

    def _extract_post_id(self, url: str) -> str:
        """Extracts the numeric post ID from a Facebook URL."""
        if not url:
            return ""
        unquoted = urllib.parse.unquote(url)
        for pattern in [
            r"multi_permalinks=([^&]+)",
            r"/posts/([^/?#&]+)",
            r"/permalink/([^/?#&]+)",
            r"story_fbid=([^&]+)",
            r"fbid=([^&]+)",
        ]:
            m = re.search(pattern, unquoted)
            if m:
                return m.group(1)
        return ""

    def _clean_url(self, raw_url: str) -> str:
        """Extracts direct canonical Facebook URL from notification link."""
        if not raw_url:
            return ""

        unquoted = urllib.parse.unquote(raw_url)

        # Pattern 1: groups/<id>/?...multi_permalinks=<id>
        m_multi = re.search(r"groups/([^/?#&]+)/.*?multi_permalinks=([^&]+)", unquoted, re.IGNORECASE)
        if m_multi:
            group_id = m_multi.group(1)
            post_id = m_multi.group(2)
            if group_id != "feed":
                return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/"

        # Pattern 2: groups/<id>/posts/<id>
        m = re.search(r"groups/([^/?#&]+)/posts/([^/?#&]+)", unquoted, re.IGNORECASE)
        if m:
            return f"https://www.facebook.com/groups/{m.group(1)}/posts/{m.group(2)}/"

        # Pattern 3: groups/<id>/permalink/<id>
        m2 = re.search(r"groups/([^/?#&]+)/permalink/([^/?#&]+)", unquoted, re.IGNORECASE)
        if m2:
            return f"https://www.facebook.com/groups/{m2.group(1)}/posts/{m2.group(2)}/"

        # Pattern 4: story_fbid=<post_id>&id=<owner_id>
        m_story = re.search(r"story_fbid=([^&]+).*?id=([^&]+)", unquoted, re.IGNORECASE)
        if m_story:
            return f"https://www.facebook.com/permalink.php?story_fbid={m_story.group(1)}&id={m_story.group(2)}"

        # Strip notification tracking parameters
        parsed = urllib.parse.urlparse(unquoted)
        clean = f"https://www.facebook.com{parsed.path}"
        return clean if parsed.path and parsed.path != "/" else raw_url

    def _extract_author_and_group(self, text: str) -> tuple[str, str]:
        """Parses group name and author from notification text."""
        clean_text = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", text).strip()
        # Pattern 1: [Group Name] has a new post.
        m1 = re.search(
            r"^(.+?)\s+(?:has\s+(?:a|\d+)\s+new\s+posts?|added\s+a\s+new\s+post)",
            clean_text,
            re.IGNORECASE,
        )
        if m1:
            return "Group Member", m1.group(1).strip()

        # Pattern 2: [Author] posted in [Group Name]
        m2 = re.search(
            r"^(.+?)\s+(?:posted|shared a post)\s+in\s+([^:\"]+)",
            clean_text,
            re.IGNORECASE,
        )
        if m2:
            return m2.group(1).strip(), m2.group(2).strip()

        # Pattern 3: New post in [Group Name] by [Author]
        m3 = re.search(r"new post in\s+(.+?)\s+by\s+(.+)", clean_text, re.IGNORECASE)
        if m3:
            return m3.group(2).strip(), m3.group(1).strip()

        # Pattern 4: Now in [Group Name]: "[Snippet]"
        m4 = re.search(r"^Now in\s+([^:\"]+):", clean_text, re.IGNORECASE)
        if m4:
            return "Group Member", m4.group(1).strip()

        return "Facebook Member", "Facebook Group"
