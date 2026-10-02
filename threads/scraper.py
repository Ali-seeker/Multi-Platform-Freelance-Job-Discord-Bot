"""
threads/scraper.py — High-speed HTTP scraper for Meta's Threads (threads.net).
Extracts public search posts from preloaded Relay JSON data headlessly using curl_cffi.
Requires 0 Selenium and 0 headless browser overhead.
"""

import json
import re
import urllib.parse
from datetime import datetime, timezone
from curl_cffi import requests

from threads.config import THREADS_SESSION_ID, JOBS_PER_PAGE
from logger import get_logger

logger = get_logger(__name__)

THREADS_SEARCH_URL = "https://www.threads.net/search"


class ThreadsScraper:
    """
    Direct HTTP scraper for Threads search and recent posts.
    Uses Chrome 124 TLS fingerprinting to bypass anti-bot challenges headlessly.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        if THREADS_SESSION_ID:
            self.session.cookies.set("sessionid", THREADS_SESSION_ID, domain=".threads.net")

    def fetch_jobs(self, query: str, limit: int = JOBS_PER_PAGE) -> list[dict]:
        """
        Searches Threads for recent posts matching the query.
        Returns a list of standardized job dictionaries.
        """
        if not query:
            return []

        encoded_query = urllib.parse.quote_plus(query.strip())
        target_url = f"{THREADS_SEARCH_URL}?q={encoded_query}&serp_type=default&filter=recent"

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
            resp = self.session.get(target_url, headers=headers, timeout=20)
        except Exception as e:
            logger.error(f"[THREADS] Network error fetching search for '{query}': {e}")
            return []

        if resp.status_code != 200:
            logger.warning(f"[THREADS] HTTP {resp.status_code} while searching for '{query}'.")
            return []

        html_text = resp.text
        return self._extract_posts_from_html(html_text, query, limit)

    def _extract_posts_from_html(self, html: str, query: str, limit: int) -> list[dict]:
        """
        Locates and extracts post objects from the preloaded Relay JSON scripts.
        """
        scripts = re.findall(
            r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )

        raw_posts = []
        for sc in scripts:
            # Quick check if script contains search results or thread posts
            if not ("caption" in sc or "thread_items" in sc or "searchResults" in sc):
                continue

            try:
                data = json.loads(sc)
            except Exception:
                continue

            extracted = self._find_post_nodes(data)
            if extracted:
                raw_posts.extend(extracted)

        # Standardize and deduplicate
        seen_ids = set()
        jobs = []

        for p in raw_posts:
            parsed = self._normalize_post(p, query)
            if not parsed:
                continue

            post_id = parsed["job_id"]
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            jobs.append(parsed)
            if len(jobs) >= limit:
                break

        return jobs

    def _find_post_nodes(self, obj) -> list[dict]:
        """
        Recursively traverses nested dictionaries and lists to locate post nodes.
        """
        posts = []
        if isinstance(obj, dict):
            # Check direct post node with caption
            if "caption" in obj and isinstance(obj["caption"], dict) and "text" in obj["caption"]:
                posts.append(obj)
            # Check thread_items node
            elif "thread_items" in obj and isinstance(obj["thread_items"], list):
                for ti in obj["thread_items"]:
                    if isinstance(ti, dict) and "post" in ti and isinstance(ti["post"], dict):
                        posts.append(ti["post"])

            for v in obj.values():
                posts.extend(self._find_post_nodes(v))
        elif isinstance(obj, list):
            for item in obj:
                posts.extend(self._find_post_nodes(item))

        return posts

    def _normalize_post(self, post_node: dict, query: str) -> dict | None:
        """
        Normalizes a raw Threads post dictionary into the bot's standard job schema.
        """
        caption_obj = post_node.get("caption") or {}
        caption_text = caption_obj.get("text", "").strip() if isinstance(caption_obj, dict) else ""
        if not caption_text:
            return None

        # Clean bidi & invisible formatting marks
        clean_text = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", caption_text).strip()
        if len(clean_text) < 15:
            return None

        user_obj = post_node.get("user") or {}
        username = user_obj.get("username", "threads_user")
        full_name = user_obj.get("full_name", "")
        profile_pic = user_obj.get("profile_pic_url", "")
        is_verified = user_obj.get("is_verified", False)

        code = post_node.get("code") or ""
        post_id = str(post_node.get("id") or code).strip()

        if code and username:
            post_url = f"https://www.threads.net/@{username}/post/{code}"
        elif code:
            post_url = f"https://www.threads.net/t/{code}"
        else:
            post_url = f"https://www.threads.net/@{username}"

        # Creation timestamp
        taken_at = post_node.get("taken_at")
        if taken_at:
            try:
                posted_iso = datetime.fromtimestamp(int(taken_at), tz=timezone.utc).isoformat()
            except Exception:
                posted_iso = datetime.now(timezone.utc).isoformat()
        else:
            posted_iso = datetime.now(timezone.utc).isoformat()

        # Derive a clean title from the first line or sentence
        title = clean_text
        for line in clean_text.splitlines():
            cand = line.strip()
            if 10 <= len(cand) <= 120 and not cand.startswith("http"):
                title = cand
                break
        if len(title) > 120:
            title = title[:117] + "..."

        author_display = f"@{username}"
        if full_name:
            author_display = f"{full_name} (@{username})"
        if is_verified:
            author_display += " ☑️"

        like_count = post_node.get("like_count")
        reply_info = post_node.get("text_post_app_info") or {}
        reply_count = reply_info.get("reply_count") if isinstance(reply_info, dict) else None

        return {
            "job_id": code or post_id,
            "title": title,
            "description": clean_text,
            "url": post_url,
            "budget": "Not specified",
            "skills": query,
            "posted_time": posted_iso,
            "author": author_display,
            "author_username": username,
            "author_avatar": profile_pic,
            "like_count": like_count,
            "reply_count": reply_count,
            "query_label": query,
        }
