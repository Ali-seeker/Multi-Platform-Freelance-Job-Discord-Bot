"""
scraper.py — Upwork GraphQL job scraper.

Contains:
  • UpworkScraper class — manages the HTTP session and fetches raw job data
  • parse_job() function — transforms raw GraphQL JSON into a clean dictionary

These are deliberately kept separate:
  - UpworkScraper handles *networking* (requests, auth, error handling)
  - parse_job() handles *data transformation* (extracting fields, formatting)
  This means you can change the output format without touching the HTTP logic,
  and vice versa.
"""

import re
import requests
from config import (
    GRAPHQL_URL,
    GRAPHQL_QUERY,
    REQUEST_HEADERS,
    COOKIES,
    JOBS_PER_PAGE,
)


class UpworkScraper:
    """
    Manages a persistent HTTP session to Upwork's GraphQL API.

    Uses requests.Session() so that:
    - TCP connections are reused (faster for multiple requests)
    - Headers/cookies are set once and applied to every request
    - Easy to extend later with auth refresh, retries, etc.
    """

    def __init__(self):
        self.session = requests.Session()
        # Apply all headers from config to the session
        self.session.headers.update(REQUEST_HEADERS)
        # Set cookies from the raw cookie string in .env
        # requests expects a dict, but the simplest approach is to set the
        # raw cookie header directly (Upwork sends a LOT of cookies)
        self.session.headers["cookie"] = COOKIES

    def fetch_jobs(self, search_query: str, count: int = JOBS_PER_PAGE) -> list[dict]:
        """
        Send the GraphQL query to Upwork and return parsed job data.

        Args:
            search_query: The job search term (e.g., "python developer")
            count: Number of jobs to fetch (default from config)

        Returns:
            List of clean job dictionaries (parsed by parse_job()),
            or an empty list if the request fails.
        """
        # Build the GraphQL request payload — same structure Upwork's
        # frontend sends, captured from DevTools
        payload = {
            "query": GRAPHQL_QUERY,
            "variables": {
                "requestVariables": {
                    "userQuery": search_query,
                    "sort": "recency",
                    "highlight": True,
                    "paging": {
                        "offset": 0,
                        "count": count,
                    },
                }
            },
        }

        try:
            response = self.session.post(
                GRAPHQL_URL,
                json=payload,
                params={"alias": "visitorJobSearch"},
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            print("[ERROR] Connection error -- check your internet connection.")
            return []
        except requests.exceptions.Timeout:
            print("[ERROR] Request timed out -- Upwork may be slow or blocking you.")
            return []
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Request failed: {e}")
            return []

        # --- Handle HTTP error codes with clear messages ---
        if response.status_code == 401:
            print("[ERROR] 401 Unauthorized -- your bearer token or cookies have expired!")
            print("   -> Re-capture them from Chrome DevTools and update your .env file.")
            return []

        if response.status_code == 403:
            print("[ERROR] 403 Forbidden -- Upwork is blocking this request.")
            print("   -> You may need fresh cookies, or Upwork detected bot-like behavior.")
            print(f"   Response preview: {response.text[:500]}")
            return []

        if response.status_code != 200:
            print(f"[ERROR] Unexpected status code: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return []

        # --- Parse the JSON response ---
        try:
            data = response.json()
        except ValueError:
            print("[ERROR] Response was not valid JSON.")
            print(f"   Raw response: {response.text[:500]}")
            return []

        # Navigate the nested GraphQL response structure
        # data → search → universalSearchNuxt → visitorJobSearchV1 → results
        try:
            search_data = data["data"]["search"]["universalSearchNuxt"]["visitorJobSearchV1"]
            results = search_data.get("results", [])
            paging = search_data.get("paging", {})
        except (KeyError, TypeError) as e:
            print(f"[ERROR] Unexpected response structure: {e}")
            print(f"   Response keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            # Check for GraphQL-level errors
            if "errors" in data:
                for err in data["errors"]:
                    print(f"   GraphQL error: {err.get('message', err)}")
            return []

        if not results:
            print("[WARN] No jobs found -- the search returned empty results.")
            print(f"   Total available: {paging.get('total', 'unknown')}")
            return []

        # Log what we got
        total = paging.get("total", "?")
        print(f"[OK] Fetched {len(results)} jobs (out of {total} total matches)")

        # Parse each raw job into a clean dictionary
        parsed_jobs = []
        for raw_job in results:
            try:
                parsed = parse_job(raw_job)
                parsed_jobs.append(parsed)
            except Exception as e:
                # Don't let one bad job kill the whole batch
                job_id = raw_job.get("id", "unknown")
                print(f"[WARN] Skipping job {job_id} -- parse error: {e}")

        return parsed_jobs


def parse_job(raw_job: dict) -> dict:
    """
    Extract the fields we care about from Upwork's raw GraphQL response
    into a clean, flat dictionary ready for database storage.

    This function is intentionally separate from UpworkScraper so you can:
    - Easily add/remove fields without touching the HTTP logic
    - Write unit tests against it with sample JSON
    - Reuse it if you switch to a different data source

    Args:
        raw_job: One element from the GraphQL response's "results" array

    Returns:
        Dictionary with keys: job_id, title, description, budget, skills, posted_time
    """
    # --- Job ID ---
    job_id = raw_job.get("id", "")

    # --- Title ---
    # Upwork wraps search-term matches in H^...^H markers for highlighting.
    # Example: "H^Python^H H^Developer^H" → "Python Developer"
    title = _strip_highlight_markers(raw_job.get("title", ""))

    # --- Description ---
    description = _strip_highlight_markers(raw_job.get("description", ""))

    # --- Skills ---
    # Extract skill names from the ontologySkills array
    skills_list = []
    for skill in raw_job.get("ontologySkills", []):
        skill_name = skill.get("prettyName") or skill.get("prefLabel", "")
        if skill_name:
            skills_list.append(skill_name)
    skills = ", ".join(skills_list)

    # --- Budget ---
    # Jobs can be FIXED price or HOURLY — we format them differently
    job_data = raw_job.get("jobTile", {}).get("job", {})
    budget = _format_budget(job_data)

    # --- Posted Time ---
    # Use publishTime (when clients can see it) over createTime (internal)
    posted_time = job_data.get("publishTime") or job_data.get("createTime", "")

    return {
        "job_id": job_id,
        "title": title,
        "description": description,
        "budget": budget,
        "skills": skills,
        "posted_time": posted_time,
    }


def _strip_highlight_markers(text: str) -> str:
    """
    Remove Upwork's H^...^H highlight markers from text.

    Upwork wraps matched search terms like: "H^Python^H H^Developer^H"
    We strip these to get clean text: "Python Developer"
    """
    if not text:
        return ""
    # Replace H^word^H with just the word inside
    return re.sub(r"H\^(.*?)\^H", r"\1", text)


def _format_budget(job_data: dict) -> str:
    """
    Format the budget into a human-readable string based on job type.

    Fixed price jobs have a fixedPriceAmount.
    Hourly jobs have hourlyBudgetMin and/or hourlyBudgetMax.
    Some jobs have no budget info at all.
    """
    job_type = job_data.get("jobType", "")

    if job_type == "FIXED":
        fixed = job_data.get("fixedPriceAmount")
        if fixed and fixed.get("amount"):
            return f"${fixed['amount']} (Fixed)"
        return "Fixed Price (budget not listed)"

    if job_type == "HOURLY":
        min_rate = job_data.get("hourlyBudgetMin")
        max_rate = job_data.get("hourlyBudgetMax")
        if min_rate and max_rate:
            return f"${min_rate}-${max_rate}/hr"
        if max_rate:
            return f"Up to ${max_rate}/hr"
        if min_rate:
            return f"From ${min_rate}/hr"
        return "Hourly (budget not listed)"

    return "Budget not specified"
