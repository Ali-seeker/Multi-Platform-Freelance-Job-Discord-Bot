"""
guru/scraper.py — Guru freelance jobs scraper using curl_cffi and BeautifulSoup.
"""

import re
import urllib.parse
from curl_cffi import requests
from bs4 import BeautifulSoup
from logger import get_logger

logger = get_logger(__name__)

GURU_BASE_URL = "https://www.guru.com"


class GuruScraper:
    """
    Scrapes freelance job listings from Guru.com.
    Uses curl_cffi with chrome124 impersonation for realistic browser headers.
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

    def fetch_jobs(self, search_query: str, limit: int = 10) -> list[dict]:
        """
        Fetches job postings matching a search query from Guru.com.

        Args:
            search_query: Search term (e.g., 'automation', 'python')
            limit: Maximum number of jobs to return (default 10)

        Returns:
            List of standardized job dictionaries.
        """
        encoded_query = urllib.parse.quote(search_query)
        search_url = f"{GURU_BASE_URL}/d/jobs/?q={encoded_query}"

        max_retries = 3
        html = ""
        for attempt in range(max_retries):
            try:
                response = self.session.get(search_url, timeout=25)
                if response.status_code == 200:
                    html = response.text
                    break
                logger.warning(
                    f"Guru search returned HTTP {response.status_code} (attempt {attempt + 1}/{max_retries})"
                )
            except Exception as e:
                logger.warning(f"Error requesting Guru jobs: {e} (attempt {attempt + 1}/{max_retries})")

        if not html:
            logger.error(f"Failed to fetch Guru jobs for query '{search_query}'.")
            return []

        return self.parse_jobs_html(html, search_query, limit=limit)

    def parse_jobs_html(self, html: str, search_query: str, limit: int = 10) -> list[dict]:
        """
        Parses raw HTML from Guru job search results into a clean list of dictionaries.
        """
        soup = BeautifulSoup(html, "html.parser")
        job_cards = soup.select(".jobRecord")
        if limit:
            job_cards = job_cards[:limit]

        if not job_cards:
            logger.info(f"No job cards found on Guru for query '{search_query}'.")
            return []

        parsed_jobs = []
        for card in job_cards:
            try:
                title_el = card.select_one(".jobRecord__title a")
                if not title_el:
                    continue

                title = title_el.text.strip()
                raw_href = title_el.get("href", "")
                clean_href = raw_href.split("&")[0] if "&" in raw_href else raw_href
                job_url = f"{GURU_BASE_URL}{clean_href}" if clean_href.startswith("/") else clean_href

                # Extract job ID
                gid = card.get("data-gid")
                if not gid:
                    match = re.search(r"/(\d+)", clean_href)
                    gid = match.group(1) if match else clean_href

                # Budget
                budget_el = card.select_one(".jobRecord__budget")
                budget = " ".join(budget_el.text.split()) if budget_el else "Not specified"

                # Description
                desc_el = card.select_one(".jobRecord__desc")
                desc = " ".join(desc_el.text.split()) if desc_el else ""

                # Metadata (posted time & quotes count)
                meta_el = card.select_one(".jobRecord__meta")
                meta_text = " ".join(meta_el.text.split()) if meta_el else ""

                posted_time = "Recent"
                quotes_count = "0"
                if meta_text:
                    time_match = re.search(r"Posted\s+([^•\–\—\-\|]+)", meta_text, re.IGNORECASE)
                    if time_match:
                        posted_time = time_match.group(1).strip()
                    quotes_match = re.search(r"(\d+)\s+Quotes\s+Received", meta_text, re.IGNORECASE)
                    if quotes_match:
                        quotes_count = quotes_match.group(1)

                # Skills
                skills_list = [s.text.strip() for s in card.select(".skillsList__skill") if s.text.strip()]
                skills = ", ".join(skills_list)

                parsed_jobs.append({
                    "job_id": str(gid),
                    "title": title,
                    "description": desc,
                    "budget": budget,
                    "skills": skills,
                    "posted_time": posted_time,
                    "quotes_count": quotes_count,
                    "url": job_url,
                })
            except Exception as e:
                logger.warning(f"Error parsing Guru job card: {e}")
                continue

        logger.info(f"[GURU] 📄 Parsed {len(parsed_jobs)} jobs from Guru for '{search_query}'.")
        return parsed_jobs
