"""
99freelas/scraper.py — 99freelas freelance jobs scraper using curl_cffi and BeautifulSoup.
"""

import re
import urllib.parse
from datetime import datetime, timezone
from curl_cffi import requests
from bs4 import BeautifulSoup
from logger import get_logger

logger = get_logger(__name__)

FREELAS99_BASE_URL = "https://www.99freelas.com.br"


class Freelance99Scraper:
    """
    Scrapes freelance project listings from 99freelas.com.br.
    Uses curl_cffi with chrome124 impersonation for fast SSR HTML retrieval.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update({
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        })

    def fetch_jobs(self, search_query: str, limit: int = 20) -> list[dict]:
        """
        Fetches job postings matching a search query from 99freelas.com.br.
        Automatically paginates across 99freelas search pages if limit > 10 (10 jobs/page).

        Args:
            search_query: Search term (e.g., 'automation', 'python')
            limit: Maximum number of jobs to return (default 20)

        Returns:
            List of standardized job dictionaries.
        """
        encoded_query = urllib.parse.quote(search_query)
        all_jobs = []
        page = 1
        max_pages = max(1, (limit + 9) // 10)

        while page <= max_pages and len(all_jobs) < limit:
            search_url = f"{FREELAS99_BASE_URL}/projects?q={encoded_query}&page={page}"

            max_retries = 3
            html = ""
            for attempt in range(max_retries):
                try:
                    response = self.session.get(search_url, timeout=25)
                    if response.status_code == 200:
                        html = response.content.decode("utf-8", errors="replace")
                        break
                    logger.warning(
                        f"99freelas search returned HTTP {response.status_code} on page {page} (attempt {attempt + 1}/{max_retries})"
                    )
                except Exception as e:
                    logger.warning(
                        f"Error requesting 99freelas jobs on page {page}: {e} (attempt {attempt + 1}/{max_retries})"
                    )

            if not html:
                logger.error(f"Failed to fetch 99freelas jobs for query '{search_query}' on page {page}.")
                break

            remaining = limit - len(all_jobs)
            page_jobs = self.parse_jobs_html(html, search_query, limit=remaining)
            if not page_jobs:
                break

            all_jobs.extend(page_jobs)
            if len(page_jobs) < 10:
                # Less than full page indicates last page reached
                break

            page += 1

        return all_jobs[:limit]

    def parse_jobs_html(self, html: str, search_query: str, limit: int = 10) -> list[dict]:
        """
        Parses 99freelas project cards from HTML.
        """
        soup = BeautifulSoup(html, "html.parser")
        result_items = soup.select("li.result-item")

        jobs = []
        for item in result_items:
            if len(jobs) >= limit:
                break

            job_id = item.get("data-id", "").strip()

            # Title and Link
            title_el = item.select_one("h1.title a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            rel_href = title_el.get("href", "")
            # Clean href: remove query parameters like ?fs=t
            clean_href = rel_href.split("?")[0] if rel_href else ""
            if clean_href.startswith("/"):
                job_url = f"{FREELAS99_BASE_URL}{clean_href}"
            elif clean_href.startswith("http"):
                job_url = clean_href
            else:
                job_url = f"{FREELAS99_BASE_URL}/{clean_href}"

            if not job_id:
                # Fallback: extract ID from URL slug (e.g. /project/slug-12345)
                id_match = re.search(r"-(\d+)$", clean_href)
                if id_match:
                    job_id = id_match.group(1)
                else:
                    job_id = clean_href

            # Description
            desc_el = item.select_one("div.item-text.description")
            description = desc_el.get_text("\n", strip=True) if desc_el else ""

            # Posted Time from <b class="datetime" cp-datetime="1790615190000">
            posted_time = ""
            epoch_sec = 0
            dt_el = item.select_one("b.datetime")
            if dt_el and dt_el.get("cp-datetime"):
                try:
                    cp_val = int(dt_el.get("cp-datetime"))
                    # If milliseconds, convert to seconds
                    epoch_sec = cp_val // 1000 if cp_val > 1e11 else cp_val
                    posted_dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
                    posted_time = posted_dt.isoformat()
                except Exception:
                    posted_time = ""

            # Information line: Category, Experience level, Proposals, Interested
            info_el = item.select_one("p.item-text.information")
            info_text = info_el.get_text(" | ", strip=True) if info_el else ""

            # Experience Level
            experience_level = ""
            for level in ["Iniciante", "Intermediário", "Especialista"]:
                if level.lower() in info_text.lower():
                    experience_level = level
                    break

            # Proposals count
            proposals_count = "0"
            if info_el:
                prop_match = re.search(r"Propostas:\s*<b>(\d+)</b>", info_el.decode_contents(), re.IGNORECASE)
                if prop_match:
                    proposals_count = prop_match.group(1)
                else:
                    prop_text_match = re.search(r"Propostas:\s*(\d+)", info_text, re.IGNORECASE)
                    if prop_text_match:
                        proposals_count = prop_text_match.group(1)

            # Skills
            skill_tags = item.select("p.item-text.habilidades a")
            skills_list = [s.get_text(strip=True) for s in skill_tags if s.get_text(strip=True)]
            skills_str = ", ".join(skills_list)

            # Client Info
            client_el = item.select_one("p.item-text.client")
            client_info = client_el.get_text(" ", strip=True) if client_el else ""
            # Strip leading "Cliente:" if present and collapse whitespace
            client_clean = re.sub(r"^Cliente:\s*", "", client_info, flags=re.IGNORECASE)
            client_name = re.sub(r"\s+", " ", client_clean).strip()

            # Budget
            budget = "A combinar / Por proposta"

            jobs.append({
                "job_id": job_id,
                "title": title,
                "url": job_url,
                "description": description,
                "budget": budget,
                "skills": skills_str,
                "posted_time": posted_time,
                "epoch_sec": epoch_sec,
                "experience_level": experience_level or "Não especificado",
                "proposals_count": proposals_count,
                "client_name": client_name or "Anônimo",
                "search_query": search_query,
            })

        return jobs
