"""
truelancer/scraper.py — Truelancer freelance jobs scraper.
Extracts structured project entities from Next.js server-side rendered __NEXT_DATA__.
"""

import json
import time
import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests
from logger import get_logger

logger = get_logger(__name__)

TRUELANCER_BASE_URL = "https://www.truelancer.com"
CURRENCY_SYMBOLS = {
    "USD": "$",
    "GBP": "£",
    "EUR": "€",
    "INR": "₹",
    "AUD": "A$",
    "CAD": "C$",
}


class TruelancerScraper:
    """
    Scrapes freelance jobs from Truelancer.com by parsing __NEXT_DATA__ in SSR HTML.
    Uses curl_cffi with chrome124 impersonation.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update({
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "referer": "https://www.truelancer.com/",
        })

    def fetch_jobs(self, search_query: str, limit: int = 15) -> list[dict]:
        """
        Fetches active job listings matching search_query from Truelancer.
        Automatically paginates across search pages when limit > 15.

        Args:
            search_query: Search term (e.g., 'automation', 'python') or custom Truelancer URL
            limit: Maximum number of jobs to return (default 15)

        Returns:
            List of standardized job dictionaries.
        """
        raw_query = search_query.strip()
        query_param = raw_query

        # If a full URL is passed, extract query parameter if present
        if raw_query.startswith("http://") or raw_query.startswith("https://"):
            parsed = urllib.parse.urlparse(raw_query)
            params = urllib.parse.parse_qs(parsed.query)
            query_param = params.get("q", [None])[0] or params.get("search", [""])[0]

        encoded_query = urllib.parse.quote(query_param)
        all_jobs = []
        page = 1
        max_pages = max(1, (limit + 14) // 15)

        while page <= max_pages and len(all_jobs) < limit:
            search_url = f"{TRUELANCER_BASE_URL}/freelance-jobs?page={page}&q={encoded_query}"

            max_retries = 3
            html = ""
            for attempt in range(max_retries):
                try:
                    response = self.session.get(search_url, timeout=25)
                    if response.status_code == 200:
                        html = response.text
                        break
                    elif response.status_code == 429:
                        wait_sec = 2 ** (attempt + 1)
                        logger.warning(
                            f"Truelancer rate-limited (429) on page {page} -- waiting {wait_sec}s before retry (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(wait_sec)
                    else:
                        logger.warning(
                            f"Truelancer returned HTTP {response.status_code} on page {page} (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(1)
                except Exception as e:
                    logger.warning(
                        f"Error requesting Truelancer on page {page}: {e} (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(1)

            if not html:
                logger.error(f"Failed to fetch Truelancer jobs for '{search_query}' on page {page}.")
                break

            remaining = limit - len(all_jobs)
            page_jobs = self.parse_projects_from_html(html, search_query, limit=remaining)
            if not page_jobs:
                break

            all_jobs.extend(page_jobs)
            if len(page_jobs) < 15:
                # Last page reached
                break

            page += 1

        pages_scraped = page if all_jobs else 0
        logger.info(f"[TRUELANCER] 📄 Scraped {len(all_jobs)} total jobs across {pages_scraped} page(s) from Truelancer for '{search_query}'.")
        return all_jobs

    def parse_projects_from_html(self, html: str, search_query: str, limit: int = 15) -> list[dict]:
        """
        Extracts and parses project entities from __NEXT_DATA__ in the HTML.
        """
        soup = BeautifulSoup(html, "html.parser")
        next_data_script = soup.find("script", id="__NEXT_DATA__")
        if not next_data_script or not next_data_script.string:
            logger.warning(f"Could not find __NEXT_DATA__ script for '{search_query}'.")
            return []

        try:
            d = json.loads(next_data_script.string)
        except Exception as e:
            logger.error(f"Failed to parse Truelancer __NEXT_DATA__ JSON: {e}")
            return []

        projects_list = (
            d.get("props", {})
            .get("pageProps", {})
            .get("data", {})
            .get("projects", {})
            .get("data", [])
        )

        if not projects_list:
            return []

        parsed_jobs = []
        for p in projects_list:
            if len(parsed_jobs) >= limit:
                break

            try:
                pid = str(p.get("id", ""))
                title = p.get("title", "Untitled Project").strip()
                desc = p.get("description", "").strip()

                currency = p.get("currency", "USD")
                sign = CURRENCY_SYMBOLS.get(currency, currency)
                raw_budget = p.get("budget", 0)
                job_type = p.get("jobTypeName", "Fixed Price")

                if raw_budget:
                    budget_str = f"{sign}{raw_budget:,.0f} {currency} ({job_type})"
                else:
                    budget_str = f"{job_type} ({currency})"

                # Skills list extraction
                raw_skills = p.get("skills", [])
                skill_names = []
                for s in raw_skills:
                    if isinstance(s, dict):
                        name = s.get("name") or s.get("tagName") or s.get("tag")
                        if name:
                            skill_names.append(name.strip())
                    elif isinstance(s, str):
                        skill_names.append(s.strip())
                skills_str = ", ".join(skill_names)

                posted_dt = str(p.get("created_at", ""))
                proposals_count = str(p.get("total_proposals", 0))

                url = p.get("link") or f"{TRUELANCER_BASE_URL}/freelance-project/{pid}"

                parsed_jobs.append({
                    "job_id": pid,
                    "title": title,
                    "description": desc,
                    "budget": budget_str,
                    "skills": skills_str,
                    "posted_time": posted_dt,
                    "proposal_count": proposals_count,
                    "project_type": job_type,
                    "url": url,
                    "currency": currency,
                })
            except Exception as e:
                logger.warning(f"Error parsing Truelancer project: {e}")
                continue

        logger.debug(f"[TRUELANCER] Parsed {len(parsed_jobs)} jobs from current page for '{search_query}'.")
        return parsed_jobs
