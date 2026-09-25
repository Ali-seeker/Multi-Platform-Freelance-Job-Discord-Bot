"""
upwork/scraper.py — Upwork GraphQL job scraper and data parser.
"""

import re
import os
import time
from curl_cffi import requests
from dotenv import set_key
from upwork.config import (
    GRAPHQL_URL,
    GRAPHQL_QUERY,
    JOB_DETAILS_QUERY,
    REQUEST_HEADERS,
    COOKIES,
    JOBS_PER_PAGE,
)
from upwork.auth_manager import SessionExpiredError
from logger import get_logger

logger = get_logger(__name__)

# Root directory path for updating .env file
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class UpworkScraper:
    """
    Manages a persistent HTTP session to Upwork's GraphQL API.
    """

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update(REQUEST_HEADERS)
        self.session.headers["cookie"] = COOKIES

    def update_session(self, auth_header: str, cookie_string: str):
        """
        Update the session's Authorization header and Cookie string
        with fresh values from AuthManager.
        """
        self.session = requests.Session(impersonate="chrome124")
        self.session.headers.update(REQUEST_HEADERS)

        self.session.headers["authorization"] = auth_header
        if auth_header.startswith("Bearer "):
            self.session.headers["x-oauth2-global-js-token"] = auth_header[7:]
        self.session.headers["cookie"] = cookie_string

        xsrf = ""
        for part in cookie_string.split(";"):
            part = part.strip()
            if part.startswith("XSRF-TOKEN="):
                xsrf = part[len("XSRF-TOKEN=") :]
                break
        if xsrf:
            self.session.headers["x-odesk-csrf-token"] = xsrf
            self.session.headers["x-xsrf-token"] = xsrf

        visitor_id = ""
        for part in cookie_string.split(";"):
            part = part.strip()
            if part.startswith("visitor_id="):
                visitor_id = part[len("visitor_id=") :]
                break
        if visitor_id:
            self.session.headers["vnd-eo-visitorid"] = visitor_id

        # Atomically write fresh credentials to root .env
        try:
            env_path = os.path.join(ROOT_DIR, ".env")
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
        """
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
                break
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

        try:
            data = response.json()
        except ValueError:
            logger.error(
                f"Response was not valid JSON. Raw response: {response.text[:500]}"
            )
            return []

        try:
            search_data = data["data"]["search"]["universalSearchNuxt"][
                "visitorJobSearchV1"
            ]
            results = search_data.get("results", [])
            paging = search_data.get("paging", {})
        except (KeyError, TypeError) as e:
            logger.error(f"Unexpected response structure: {e}", exc_info=True)
            if "errors" in data:
                for err in data["errors"]:
                    logger.error(f"GraphQL error: {err.get('message', err)}")
            return []

        if not results:
            logger.info(
                f"No new jobs found for '{search_query}'. Total available: {paging.get('total', 'unknown')}"
            )
            return []

        total = paging.get("total", "?")
        logger.info(f"[UPWORK] 🌐 Received {len(results)} jobs for '{search_query}' (out of {total} total matches on Upwork)")

        parsed_jobs = []
        for raw_job in results:
            try:
                parsed = parse_job(raw_job)
                parsed_jobs.append(parsed)
            except Exception as e:
                job_id = raw_job.get("id", "unknown")
                logger.warning(f"Skipping job {job_id} -- parse error: {e}")

        return parsed_jobs

    def fetch_job_details(self, ciphertext: str) -> dict:
        """
        Fetch full details for a single job using its ciphertext ID.
        """
        if not ciphertext:
            return {}

        payload = {
            "query": JOB_DETAILS_QUERY,
            "variables": {
                "id": ciphertext,
                "isLoggedIn": False,
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
                logger.debug(
                    f"Job details returned {response.status_code} -- triggering reactive refresh"
                )
                raise SessionExpiredError(f"{response.status_code} on job details")
            logger.debug(f"Job details returned status {response.status_code}")
            return {}

        try:
            data = response.json()
        except ValueError:
            logger.error("Job details response was not valid JSON.")
            return {}

        if "errors" in data:
            for error in data.get("errors", []):
                code = error.get("extensions", {}).get("code", "")
                message = error.get("message", "")
                if code == "error.job.requires.account" or "Access is restricted" in message:
                    return {"is_private_job": True}

        try:
            details = data.get("data", {}).get("jobPubDetails")
            if details is None:
                return {}
        except (KeyError, TypeError) as e:
            logger.error(f"Unexpected job details structure: {e}", exc_info=True)
            return {}

        return _parse_job_details(details)


def _parse_job_details(raw_details: dict) -> dict:
    """Parse the raw job details response into a clean dictionary."""
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

    total_assignments = stats.get("totalAssignments", 0) or 0
    total_with_hires = stats.get("totalJobsWithHires", 0) or 0
    hire_rate = (
        round((total_with_hires / total_assignments) * 100)
        if total_assignments > 0
        else 0
    )

    total_charges = stats.get("totalCharges", {})
    total_spent = total_charges.get("amount", 0) if total_charges else 0

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
    """Extract fields from Upwork's GraphQL response into a clean dictionary."""
    job_id = raw_job.get("id", "")
    title = _strip_highlight_markers(raw_job.get("title", ""))
    description = _strip_highlight_markers(raw_job.get("description", ""))

    skills_list = []
    for skill in raw_job.get("ontologySkills", []):
        skill_name = skill.get("prettyName") or skill.get("prefLabel", "")
        if skill_name:
            skills_list.append(skill_name)
    skills = ", ".join(skills_list)

    job_data = raw_job.get("jobTile", {}).get("job", {})
    budget = _format_budget(job_data)
    ciphertext = job_data.get("ciphertext", "")

    tier_map = {
        "EntryLevel": "Entry Level",
        "IntermediateLevel": "Intermediate",
        "ExpertLevel": "Expert",
    }
    contractor_tier = job_data.get("contractorTier", "")
    experience_level = tier_map.get(contractor_tier, contractor_tier or "Not specified")
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
    """Remove Upwork's H^...^H highlight markers from text."""
    if not text:
        return ""
    return re.sub(r"H\^(.*?)\^H", r"\1", text)


def _format_budget(job_data: dict) -> str:
    """Format budget into human-readable string."""
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
