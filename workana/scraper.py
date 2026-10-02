"""
workana/scraper.py — High-speed HTTP scraper for Workana (workana.com).
Leverages Workana's native JSON search endpoint (&format=json) via curl_cffi Chrome 124.
Requires 0 Selenium, 0 headless browser overhead, and 0 authentication tokens.
"""

import re
import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests

from workana.config import JOBS_PER_PAGE
from logger import get_logger

logger = get_logger(__name__)

WORKANA_BASE_URL = "https://www.workana.com"
WORKANA_SEARCH_URL = "https://www.workana.com/jobs"


class WorkanaScraper:
    """
    Direct HTTP scraper for Workana marketplace job search.
    Uses Chrome 124 TLS fingerprinting to bypass anti-bot challenges and fetches
    pure JSON payloads directly from Workana's search service.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")

    def fetch_jobs(self, query: str, limit: int = JOBS_PER_PAGE) -> list[dict]:
        """
        Fetches recent freelance projects from Workana matching the specified query.
        Returns a list of standardized job dictionaries.
        """
        if not query:
            return []

        jobs = []
        page = 1
        max_pages = max(1, (limit + 9) // 10)

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        while len(jobs) < limit and page <= max_pages:
            encoded_query = urllib.parse.quote_plus(query.strip())
            url = f"{WORKANA_SEARCH_URL}?query={encoded_query}&format=json&page={page}"

            try:
                resp = self.session.get(url, headers=headers, timeout=20)
            except Exception as e:
                logger.error(f"[WORKANA] Network error searching for '{query}' (page {page}): {e}")
                break

            if resp.status_code != 200:
                logger.warning(f"[WORKANA] HTTP {resp.status_code} while searching for '{query}' (page {page}).")
                break

            try:
                data = resp.json()
            except Exception as e:
                logger.error(f"[WORKANA] Failed to decode JSON from Workana for '{query}': {e}")
                break

            results_data = data.get("results", {})
            if isinstance(results_data, dict):
                items = results_data.get("results", [])
            elif isinstance(results_data, list):
                items = results_data
            else:
                items = []

            if not items:
                break

            for item in items:
                parsed = self._normalize_project(item, query)
                if parsed:
                    jobs.append(parsed)
                    if len(jobs) >= limit:
                        break

            # If fewer than 7 items were returned, this was the last page
            if len(items) < 7:
                break

            page += 1

        return jobs[:limit]

    def _normalize_project(self, item: dict, query: str) -> dict | None:
        """
        Extracts and normalizes fields from a raw Workana project JSON dictionary.
        """
        slug = item.get("slug") or ""
        if not slug:
            return None

        # Clean title
        raw_title = item.get("title") or ""
        if "<" in raw_title:
            soup = BeautifulSoup(raw_title, "html.parser")
            title = soup.get_text(strip=True)
        else:
            title = raw_title.strip()

        if not title:
            title = slug.replace("-", " ").title()

        # Clean description
        raw_desc = item.get("description") or item.get("shortDescription") or ""
        if "<" in raw_desc:
            # Replace <br /> with newlines before stripping HTML
            desc_text = re.sub(r"<br\s*/?>", "\n", raw_desc, flags=re.IGNORECASE)
            soup_desc = BeautifulSoup(desc_text, "html.parser")
            description = soup_desc.get_text().strip()
        else:
            description = raw_desc.strip()

        # Clean country
        raw_country = item.get("country") or ""
        client_country = "International"
        if "<" in raw_country:
            soup_c = BeautifulSoup(raw_country, "html.parser")
            client_country = soup_c.get_text(strip=True) or "International"
        elif raw_country:
            client_country = raw_country.strip()

        # Budget & type
        budget = item.get("budget") or "Negotiable / To be agreed"
        is_hourly = bool(item.get("isHourly", False))

        # Skills
        raw_skills = item.get("skills") or []
        skill_names = []
        if isinstance(raw_skills, list):
            for s in raw_skills:
                if isinstance(s, dict) and s.get("anchorText"):
                    skill_names.append(s["anchorText"].strip())
                elif isinstance(s, str):
                    skill_names.append(s.strip())
        skills_str = ", ".join(skill_names) if skill_names else query

        # Proposal count
        total_bids = item.get("totalBids") or "0 proposals"
        if isinstance(total_bids, str):
            proposals = total_bids.replace("Bids:", "").strip()
        else:
            proposals = str(total_bids)

        # Client details
        client_name = item.get("authorName") or "Workana Client"
        has_verified_payment = bool(item.get("hasVerifiedPaymentMethod", False))
        rating_obj = item.get("rating")
        client_rating = "New Client"
        if isinstance(rating_obj, dict):
            val = rating_obj.get("value")
            if val and val != "0.00":
                client_rating = f"⭐ {val} / 5.0"

        # Direct project URL
        project_url = f"{WORKANA_BASE_URL}/job/{slug}"

        # Posted time
        posted_time = item.get("postedDate") or item.get("publishedDate") or "Recent"
        if isinstance(posted_time, str) and posted_time.startswith("Published:"):
            posted_time = posted_time.replace("Published:", "").strip()

        return {
            "job_id": slug,
            "title": title,
            "description": description,
            "url": project_url,
            "budget": budget,
            "is_hourly": is_hourly,
            "skills": skills_str,
            "posted_time": posted_time,
            "client_name": client_name,
            "client_country": client_country,
            "client_rating": client_rating,
            "payment_verified": has_verified_payment,
            "proposals_count": proposals,
            "query_label": query,
        }
