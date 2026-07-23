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
import os
import time
from curl_cffi import requests
from dotenv import set_key
from config import (
    GRAPHQL_URL,
    GRAPHQL_QUERY,
    JOB_DETAILS_QUERY,
    REQUEST_HEADERS,
    COOKIES,
    JOBS_PER_PAGE,
)
from auth_manager import SessionExpiredError
from logger import get_logger

logger = get_logger(__name__)


class UpworkScraper:
    """
    Manages a persistent HTTP session to Upwork's GraphQL API.

    Uses requests.Session() so that:
    - TCP connections are reused (faster for multiple requests)
    - Headers/cookies are set once and applied to every request
    - Easy to extend later with auth refresh, retries, etc.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        # Apply all headers from config to the session
        self.session.headers.update(REQUEST_HEADERS)
        # Set cookies from the raw cookie string in .env
        # requests expects a dict, but the simplest approach is to set the
        # raw cookie header directly (Upwork sends a LOT of cookies)
        self.session.headers["cookie"] = COOKIES

    def update_session(self, auth_header: str, cookie_string: str):
        """
        Update the session's Authorization header and Cookie string
        with fresh values from AuthManager.

        Also re-extracts the XSRF token and visitor_id from the new
        cookie string since Cloudflare rotates them.

        Args:
            auth_header: Fresh Authorization header value
                         (e.g., "Bearer oauth2v2_...")
            cookie_string: Fresh full cookie header string
        """
        # Recreate the session completely to force a fresh TLS handshake
        # and drop any blocked TCP connections pooled by curl_cffi
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update(REQUEST_HEADERS)

        self.session.headers["authorization"] = auth_header
        if auth_header.startswith("Bearer "):
            self.session.headers["x-oauth2-global-js-token"] = auth_header[7:]
        self.session.headers["cookie"] = cookie_string
        # Re-extract XSRF token for CSRF protection header
        xsrf = ""
        for part in cookie_string.split(";"):
            part = part.strip()
            if part.startswith("XSRF-TOKEN="):
                xsrf = part[len("XSRF-TOKEN=") :]
                break
        if xsrf:
            self.session.headers["x-odesk-csrf-token"] = xsrf
            self.session.headers["x-xsrf-token"] = xsrf
        # Re-extract visitor_id
        visitor_id = ""
        for part in cookie_string.split(";"):
            part = part.strip()
            if part.startswith("visitor_id="):
                visitor_id = part[len("visitor_id=") :]
                break
        if visitor_id:
            self.session.headers["vnd-eo-visitorid"] = visitor_id

        # Atomically write fresh credentials to .env
        try:
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            set_key(env_path, "UPWORK_BEARER_TOKEN", auth_header)
            set_key(env_path, "UPWORK_COOKIES", cookie_string)
            logger.info("💾 New credentials saved to .env")
        except Exception as e:
            logger.warning(
                f"Failed to save refreshed credentials to .env: {e}", exc_info=True
            )

        logger.info("📡 Session headers updated")

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

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    GRAPHQL_URL,
                    json=payload,
                    params={"alias": "visitorJobSearch"},
                    timeout=30,
                )
                break  # If successful, break out of retry loop
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                logger.warning(
                    f"Network error during fetch_jobs (attempt {attempt+1}/{max_retries}): {e}"
                )
                if attempt == max_retries - 1:
                    logger.error("Max retries reached for network error in fetch_jobs.")
                    return []
                time.sleep(2**attempt)
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}", exc_info=True)
                return []

        # --- Handle HTTP error codes with clear messages ---
        if response.status_code == 401:
            logger.warning(
                "401 Unauthorized -- bearer token or cookies have expired! Triggering reactive session refresh..."
            )
            raise SessionExpiredError("401 Unauthorized")

        if response.status_code == 403:
            logger.warning(
                f"403 Forbidden -- Upwork is blocking this request. Response preview: {response.text[:500]}"
            )
            raise SessionExpiredError("403 Forbidden")

        if response.status_code != 200:
            logger.error(
                f"Unexpected status code: {response.status_code} - {response.text[:500]}"
            )
            return []

        # --- Parse the JSON response ---
        try:
            data = response.json()
        except ValueError:
            logger.error(
                f"Response was not valid JSON. Raw response: {response.text[:500]}"
            )
            return []

        # Navigate the nested GraphQL response structure
        # data → search → universalSearchNuxt → visitorJobSearchV1 → results
        try:
            search_data = data["data"]["search"]["universalSearchNuxt"][
                "visitorJobSearchV1"
            ]
            results = search_data.get("results", [])
            paging = search_data.get("paging", {})
        except (KeyError, TypeError) as e:
            logger.error(f"Unexpected response structure: {e}", exc_info=True)
            logger.error(
                f"Response keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}"
            )
            # Check for GraphQL-level errors
            if "errors" in data:
                for err in data["errors"]:
                    logger.error(f"GraphQL error: {err.get('message', err)}")
            return []

        if not results:
            logger.warning(
                f"No jobs found -- the search returned empty results. Total available: {paging.get('total', 'unknown')}"
            )
            return []

        # Log what we got
        total = paging.get("total", "?")
        logger.info(f"Fetched {len(results)} jobs (out of {total} total matches)")

        # Parse each raw job into a clean dictionary
        parsed_jobs = []
        for raw_job in results:
            try:
                parsed = parse_job(raw_job)
                parsed_jobs.append(parsed)
            except Exception as e:
                # Don't let one bad job kill the whole batch
                job_id = raw_job.get("id", "unknown")
                logger.warning(f"Skipping job {job_id} -- parse error: {e}")

        return parsed_jobs

    def fetch_job_details(self, ciphertext: str) -> dict:
        """
        Fetch full details for a single job using its ciphertext ID.

        This makes a SECOND GraphQL request (different from the search query)
        to get the complete job description, client info, proposal count, etc.

        Args:
            ciphertext: The job's ciphertext ID (e.g., "~022072926869803851328")

        Returns:
            Dictionary with full job details, or empty dict on failure.
        """
        payload = {
            "query": JOB_DETAILS_QUERY,
            "variables": {
                "id": ciphertext,
                "isLoggedIn": True,
            },
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    GRAPHQL_URL,
                    json=payload,
                    params={"alias": "gql-query-get-visitor-job-details"},
                    timeout=30,
                )
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                logger.warning(
                    f"Network error during fetch_job_details (attempt {attempt+1}/{max_retries}): {e}"
                )
                if attempt == max_retries - 1:
                    logger.error(
                        "Max retries reached for network error in fetch_job_details."
                    )
                    return {}
                time.sleep(2**attempt)
            except requests.exceptions.RequestException as e:
                logger.error(f"Job details request failed: {e}", exc_info=True)
                return {}

        if response.status_code != 200:
            if response.status_code in (401, 403):
                logger.warning(
                    f"Job details returned {response.status_code} -- triggering reactive refresh"
                )
                raise SessionExpiredError(f"{response.status_code} on job details")
            logger.error(f"Job details returned status {response.status_code}")
            return {}

        try:
            data = response.json()
        except ValueError:
            logger.error("Job details response was not valid JSON.")
            return {}

        try:
            details = data.get("data", {}).get("jobPubDetails")
            if details is None:
                # Upwork returns null for jobPubDetails when the job is private, 
                # restricted, invite-only, or deleted. 
                return {"is_private_job": True}
                
            # If details is NOT null, it's a public job! We can safely parse it.
            # (We ignore the 'errors' array because Upwork sometimes sends benign 
            # OAuth warnings for public jobs, but the data is still there).
        except (KeyError, TypeError) as e:
            logger.error(f"Unexpected job details structure: {e}", exc_info=True)
            return {}

        return _parse_job_details(details)


def _parse_job_details(raw_details: dict) -> dict:
    """
    Parse the raw job details response into a clean dictionary.

    Extracts full description, client info, proposal count, experience level,
    project duration, budget details, and payment verification status.

    Args:
        raw_details: The 'jobPubDetails' object from the GraphQL response

    Returns:
        Dictionary with all extracted detail fields.
    """
    if not raw_details:
        return {}
    opening = raw_details.get("opening", {})
    buyer = raw_details.get("buyer", {})
    buyer_extra = raw_details.get("buyerExtra", {})
    info = opening.get("info", {})
    stats = buyer.get("stats", {})
    location = buyer.get("location", {})
    company = buyer.get("company", {})
    client_activity = opening.get("clientActivity", {})
    engagement = opening.get("engagementDuration", {})
    budget_info = opening.get("budget", {})
    extended_budget = opening.get("extendedBudgetInfo", {})

    # Calculate hire rate from stats
    total_assignments = stats.get("totalAssignments", 0) or 0
    total_with_hires = stats.get("totalJobsWithHires", 0) or 0
    hire_rate = (
        round((total_with_hires / total_assignments) * 100)
        if total_assignments > 0
        else 0
    )

    # Format total spent
    total_charges = stats.get("totalCharges", {})
    total_spent = total_charges.get("amount", 0) if total_charges else 0

    # Format budget string
    job_type = info.get("type", "")
    if job_type == "FIXED":
        amount = budget_info.get("amount", 0) if budget_info else 0
        budget_str = (
            f"${amount:,.0f} (Fixed Price)" if amount else "Fixed Price (not listed)"
        )
    else:
        hr_min = extended_budget.get("hourlyBudgetMin")
        hr_max = extended_budget.get("hourlyBudgetMax")
        if hr_min and hr_max:
            budget_str = f"${hr_min}-${hr_max}/hr"
        elif hr_max:
            budget_str = f"Up to ${hr_max}/hr"
        elif hr_min:
            budget_str = f"From ${hr_min}/hr"
        else:
            budget_str = "Hourly (not listed)"

    # Map contractorTier to human-readable level
    tier_map = {
        "ENTRY": "Entry Level",
        "INTERMEDIATE": "Intermediate",
        "EXPERT": "Expert",
    }
    contractor_tier = opening.get("contractorTier", "")
    experience_level = tier_map.get(contractor_tier, contractor_tier or "Not specified")

    return {
        "description": opening.get("description", ""),
        "job_type": job_type,
        "budget": budget_str,
        "experience_level": experience_level,
        "project_duration": engagement.get("label", "Not specified"),
        "category": opening.get("category", {}).get("name", ""),
        "total_applicants": client_activity.get("totalApplicants", 0),
        "total_hired": client_activity.get("totalHired", 0),
        "positions_to_hire": client_activity.get("numberOfPositionsToHire", 1),
        "client_location": f"{location.get('city', '')}, {location.get('country', '')}".strip(
            ", "
        ),
        "client_country": location.get("country", ""),
        "client_total_spent": total_spent,
        "client_total_jobs": total_assignments,
        "client_hire_rate": hire_rate,
        "client_rating": stats.get("score", 0),
        "client_member_since": company.get("contractDate", ""),
        "payment_verified": buyer_extra.get("isPaymentMethodVerified", False),
        "posted_on": opening.get("postedOn") or opening.get("publishTime", ""),
    }


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

    # --- Ciphertext (Phase 2) ---
    # Needed to build the Upwork job URL and fetch full details
    ciphertext = job_data.get("ciphertext", "")

    # --- Experience Level ---
    tier_map = {
        "EntryLevel": "Entry Level",
        "IntermediateLevel": "Intermediate",
        "ExpertLevel": "Expert",
    }
    contractor_tier = job_data.get("contractorTier", "")
    experience_level = tier_map.get(contractor_tier, contractor_tier or "Not specified")

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
        "ciphertext": ciphertext,
        "experience_level": experience_level,
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
