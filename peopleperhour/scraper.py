"""
peopleperhour/scraper.py — PeoplePerHour freelance jobs scraper.
Extracts structured project entities from server-side rendered React state.
"""

import re
import json
import urllib.parse
from curl_cffi import requests
from logger import get_logger

logger = get_logger(__name__)

PPH_BASE_URL = "https://www.peopleperhour.com"
CURRENCY_SYMBOLS = {
    "GBP": "£",
    "USD": "$",
    "EUR": "€",
}


class PeoplePerHourScraper:
    """
    Scrapes freelance jobs from PeoplePerHour.com by parsing window.PPHReact.initialState.
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
        })

    def fetch_jobs(self, search_query: str, limit: int = 20) -> list[dict]:
        """
        Fetches active job listings matching search_query from PeoplePerHour.
        Automatically paginates across search pages when limit > 20.

        Args:
            search_query: Search term (e.g., 'automation', 'python')
            limit: Maximum number of jobs to return (default 20)

        Returns:
            List of standardized job dictionaries.
        """
        encoded_query = urllib.parse.quote(search_query)
        all_jobs = []
        page = 1
        max_pages = max(1, (limit + 19) // 20)

        while page <= max_pages and len(all_jobs) < limit:
            search_url = f"{PPH_BASE_URL}/freelance-jobs?q={encoded_query}&sort=latest&page={page}"

            max_retries = 3
            html = ""
            for attempt in range(max_retries):
                try:
                    response = self.session.get(search_url, timeout=25)
                    if response.status_code == 200:
                        html = response.text
                        break
                    logger.warning(
                        f"PeoplePerHour returned HTTP {response.status_code} on page {page} (attempt {attempt + 1}/{max_retries})"
                    )
                except Exception as e:
                    logger.warning(
                        f"Error requesting PeoplePerHour on page {page}: {e} (attempt {attempt + 1}/{max_retries})"
                    )

            if not html:
                logger.error(f"Failed to fetch PeoplePerHour jobs for '{search_query}' on page {page}.")
                break

            remaining = limit - len(all_jobs)
            page_jobs = self.parse_projects_from_html(html, search_query, limit=remaining)
            if not page_jobs:
                break

            all_jobs.extend(page_jobs)
            if len(page_jobs) < 20:
                # Reached last page of results
                break

            page += 1

        pages_scraped = page if all_jobs else 0
        logger.info(f"[PEOPLEPERHOUR] 📄 Scraped {len(all_jobs)} total jobs across {pages_scraped} page(s) from PeoplePerHour for '{search_query}'.")
        return all_jobs

    def parse_projects_from_html(self, html: str, search_query: str, limit: int = 20) -> list[dict]:
        """
        Extracts and parses project entities from window.PPHReact.initialState in the HTML.
        """
        # Match window.PPHReact.initialState = { ... };
        m = re.search(r"window\.PPHReact\.initialState\s*=\s*(\{.*?\});\s*(?:window|\n|<)", html)
        if not m:
            logger.warning(f"Could not find window.PPHReact.initialState for '{search_query}'.")
            return []

        try:
            state = json.loads(m.group(1))
        except Exception as e:
            logger.error(f"Failed to parse PPHReact JSON state: {e}")
            return []

        projects_dict = state.get("entities", {}).get("projects", {})
        if not projects_dict:
            return []

        parsed_jobs = []
        for raw_proj in projects_dict.values():
            if len(parsed_jobs) >= limit:
                break

            try:
                attr = raw_proj.get("attributes", {})
                pid = str(attr.get("proj_id") or raw_proj.get("id", ""))
                title = attr.get("title", "Untitled Project").strip()
                desc = attr.get("proj_desc", "").strip()

                currency = attr.get("currency", "GBP")
                sign = CURRENCY_SYMBOLS.get(currency, currency)
                raw_budget = attr.get("budget", 0)
                proj_type = attr.get("project_type", "fixed")

                if proj_type == "hourly":
                    budget_str = f"{sign}{raw_budget:,.0f}/hr {currency}" if raw_budget else f"Hourly ({currency})"
                    type_label = "Hourly Project"
                else:
                    budget_str = f"{sign}{raw_budget:,.0f} {currency} (Fixed)" if raw_budget else f"Fixed Price ({currency})"
                    type_label = "Fixed Price"

                # Category and tags as skills
                category = attr.get("category", {}).get("cate_name", "")
                sub_category = attr.get("sub_category", {}).get("subcate_name", "")
                tags = [t for t in [category, sub_category] if t]
                skills = ", ".join(tags)

                posted_dt = str(attr.get("posted_dt", ""))
                proposal_count = str(attr.get("proposalCount", 0))

                url = attr.get("url") or f"{PPH_BASE_URL}/freelance-jobs/{pid}"

                parsed_jobs.append({
                    "job_id": pid,
                    "title": title,
                    "description": desc,
                    "budget": budget_str,
                    "skills": skills,
                    "posted_time": posted_dt,
                    "proposal_count": proposal_count,
                    "project_type": type_label,
                    "url": url,
                    "currency": currency,
                })
            except Exception as e:
                logger.warning(f"Error parsing PeoplePerHour project: {e}")
                continue

        logger.debug(f"[PEOPLEPERHOUR] Parsed {len(parsed_jobs)} jobs from current page for '{search_query}'.")
        return parsed_jobs
