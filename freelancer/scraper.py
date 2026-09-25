"""
freelancer/scraper.py — Freelancer.com REST API client and project parser.
"""

import urllib.parse
from curl_cffi import requests
from logger import get_logger

logger = get_logger(__name__)

FREELANCER_API_BASE = "https://www.freelancer.com/api/projects/0.1"


class FreelancerScraper:
    """
    Scrapes active project listings from Freelancer.com's public REST API.
    Uses curl_cffi with chrome124 impersonation.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update({
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        })

    def fetch_jobs(self, search_query: str, limit: int = 20) -> list[dict]:
        """
        Fetches active projects matching a search query from Freelancer.com.
        Orders by time_submitted (newest first).

        Args:
            search_query: Search term (e.g., 'automation', 'python')
            limit: Maximum number of projects to return (default 20)

        Returns:
            List of standardized job dictionaries.
        """
        all_projects = []
        offset = 0
        batch_size = min(limit, 100)

        while len(all_projects) < limit:
            fetch_count = min(batch_size, limit - len(all_projects))
            params = {
                "query": search_query,
                "limit": fetch_count,
                "offset": offset,
                "sort_field": "time_submitted",
                "job_details": "true",
                "full_description": "true",
                "compact": "true",
            }

            max_retries = 3
            data = None
            for attempt in range(max_retries):
                try:
                    response = self.session.get(
                        f"{FREELANCER_API_BASE}/projects/active/",
                        params=params,
                        timeout=25,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        break
                    logger.warning(
                        f"Freelancer API returned HTTP {response.status_code} (attempt {attempt + 1}/{max_retries})"
                    )
                except Exception as e:
                    logger.warning(
                        f"Error querying Freelancer API: {e} (attempt {attempt + 1}/{max_retries})"
                    )

            if not data or "result" not in data:
                logger.error(f"Failed to fetch Freelancer projects for query '{search_query}'.")
                break

            projects = data.get("result", {}).get("projects", [])
            if not projects:
                break

            for raw_p in projects:
                try:
                    parsed = self.parse_project(raw_p)
                    all_projects.append(parsed)
                except Exception as e:
                    logger.warning(f"Error parsing Freelancer project {raw_p.get('id')}: {e}")

            if len(projects) < fetch_count:
                # No more projects available on API
                break

            offset += len(projects)

        logger.info(f"[FREELANCER] 📄 Scraped {len(all_projects)} total jobs from Freelancer for '{search_query}'.")
        return all_projects

    def parse_project(self, raw_p: dict) -> dict:
        """Standardizes raw Freelancer API project into a clean dictionary."""
        pid = str(raw_p.get("id", ""))
        title = raw_p.get("title", "Untitled Project").strip()
        description = raw_p.get("description", "").strip()
        seo_url = raw_p.get("seo_url", "")
        project_url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else f"https://www.freelancer.com/projects/{pid}"

        time_submitted = str(raw_p.get("time_submitted", ""))
        project_type = raw_p.get("type", "fixed")
        currency = raw_p.get("currency", {})
        currency_code = currency.get("code", "USD")
        currency_sign = currency.get("sign", "$")

        budget_str = self._format_budget(raw_p, currency_sign, currency_code, project_type)

        # Skills / Jobs
        skills_list = [j.get("name", "").strip() for j in raw_p.get("jobs", []) if j.get("name")]
        skills = ", ".join(skills_list)

        # Bids count & avg
        bid_stats = raw_p.get("bid_stats", {}) or {}
        bids_count = str(bid_stats.get("bid_count", 0))

        return {
            "job_id": pid,
            "title": title,
            "description": description,
            "budget": budget_str,
            "skills": skills,
            "posted_time": time_submitted,
            "bids_count": bids_count,
            "project_type": "Fixed Price" if project_type == "fixed" else "Hourly Project",
            "url": project_url,
            "currency": currency_code,
        }

    def _format_budget(self, raw_p: dict, sign: str, code: str, p_type: str) -> str:
        """Formats the budget range and currency into a clean human-readable string."""
        budget = raw_p.get("budget", {}) or {}
        min_amt = budget.get("minimum")
        max_amt = budget.get("maximum")

        hourly_info = raw_p.get("hourly_project_info") or {}
        if p_type == "hourly" and hourly_info:
            h_min = hourly_info.get("commitment", {}).get("hours")
            if min_amt and max_amt:
                return f"{sign}{min_amt:,.0f} - {sign}{max_amt:,.0f}/hr {code}"
            elif max_amt:
                return f"Up to {sign}{max_amt:,.0f}/hr {code}"
            elif min_amt:
                return f"From {sign}{min_amt:,.0f}/hr {code}"
            return f"Hourly ({code})"

        if min_amt and max_amt:
            return f"{sign}{min_amt:,.0f} - {sign}{max_amt:,.0f} {code}"
        elif max_amt:
            return f"Up to {sign}{max_amt:,.0f} {code}"
        elif min_amt:
            return f"From {sign}{min_amt:,.0f} {code}"

        return "Budget not specified"
