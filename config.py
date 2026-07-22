"""
config.py — Loads all configuration from .env into a clean namespace.

Nothing is hardcoded here. Every value comes from environment variables.
If a required variable is missing, we fail fast with a clear error message
so you know exactly what to fix.
"""

import os
import sys
import json
from dotenv import load_dotenv

from logger import get_logger

logger = get_logger(__name__)

# Load .env file from the project root
load_dotenv()


def _require_env(key: str) -> str:
    """Get an environment variable or exit with a helpful error."""
    value = os.getenv(key)
    if not value:
        logger.error(f"Missing required environment variable: {key}")
        logger.error("   -> Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    return value


# --- Authentication --------------------------------------------------------
# Bearer token from the "authorization" header in DevTools
BEARER_TOKEN = _require_env("UPWORK_BEARER_TOKEN")

# Full cookie string from the "cookie" header in DevTools
COOKIES = _require_env("UPWORK_COOKIES")

# --- Search ----------------------------------------------------------------
JOBS_PER_PAGE = int(os.getenv("UPWORK_JOBS_PER_PAGE", "10"))

# Load config.json
CONFIG_JSON_PATH = os.path.join(os.path.dirname(__file__), "config.json")
try:
    with open(CONFIG_JSON_PATH, "r") as f:
        _config_data = json.load(f)
    TRACKED_URLS = _config_data.get("tracked_urls", [])
    POLL_INTERVAL_SECONDS = _config_data.get(
        "fetch_interval", int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
    )
except Exception as e:
    logger.error(f"Could not load config.json: {e}")
    TRACKED_URLS = []
    POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
    _config_data = {"tracked_urls": [], "fetch_interval": POLL_INTERVAL_SECONDS}


def add_new_tracker(url: str, channel_id: str, label: str):
    """Adds a new tracker to the config.json file and the in-memory list."""
    new_entry = {"url": url, "channel_id": channel_id, "label": label}
    TRACKED_URLS.append(new_entry)
    _config_data["tracked_urls"] = TRACKED_URLS

    with open(CONFIG_JSON_PATH, "w") as f:
        json.dump(_config_data, f, indent=4)
    logger.info(f"💾 Added new tracker to config.json: {label}")


def remove_tracker_by_label(label: str):
    """Removes a tracker from config.json and memory by label. Returns the removed entry if found."""
    global TRACKED_URLS
    for i, entry in enumerate(TRACKED_URLS):
        if entry.get("label", "").lower() == label.lower():
            removed = TRACKED_URLS.pop(i)
            _config_data["tracked_urls"] = TRACKED_URLS
            with open(CONFIG_JSON_PATH, "w") as f:
                json.dump(_config_data, f, indent=4)
            logger.info(f"🗑️ Removed tracker from config.json: {label}")
            return removed
    return None


def update_tracker_by_label(old_label: str, new_label: str, new_url: str):
    """Updates a tracker's label and url in config.json and memory. Returns the updated entry if found."""
    global TRACKED_URLS
    for entry in TRACKED_URLS:
        if entry.get("label", "").lower() == old_label.lower():
            entry["label"] = new_label
            entry["url"] = new_url
            _config_data["tracked_urls"] = TRACKED_URLS
            with open(CONFIG_JSON_PATH, "w") as f:
                json.dump(_config_data, f, indent=4)
            logger.info(
                f"🔄 Updated tracker in config.json: {old_label} -> {new_label}"
            )
            return entry
    return None


# --- Discord ---------------------------------------------------------------
# Bot token from the Discord Developer Portal
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
# Channel ID fallback
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "")

# --- Upwork API Details ----------------------------------------------------
# These are constants derived from the captured request, not user secrets.
# They define *where* and *how* we talk to Upwork's API.
GRAPHQL_URL = "https://www.upwork.com/api/graphql/v1"


def _extract_cookie_value(cookie_string: str, cookie_name: str) -> str:
    """Extract a specific cookie's value from the raw cookie header string."""
    for part in cookie_string.split(";"):
        part = part.strip()
        if part.startswith(f"{cookie_name}="):
            return part[len(cookie_name) + 1 :]
    return ""


# Extract the XSRF token from cookies — Upwork requires it as a header
# for CSRF protection. Without it, you get 403 Forbidden.
_xsrf_token = _extract_cookie_value(COOKIES, "XSRF-TOKEN")

# Extract visitor ID from cookies for the tracing header
_visitor_id = _extract_cookie_value(COOKIES, "visitor_id")

# Headers that mimic a real browser request.
# The cookie and authorization values are injected from .env at runtime.
REQUEST_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "authorization": BEARER_TOKEN,
    "content-type": "application/json",
    "origin": "https://www.upwork.com",
    "referer": "https://www.upwork.com/nx/search/jobs/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
    "x-upwork-accept-language": "en-US",
    "x-odesk-csrf-token": _xsrf_token,
    "x-xsrf-token": _xsrf_token,
    "vnd-eo-visitorid": _visitor_id,
}

# The GraphQL query string — this is the exact query Upwork's frontend sends.
# We captured it from DevTools and keep it here verbatim so we get the same
# response shape their frontend expects.
GRAPHQL_QUERY = """
  query VisitorJobSearch($requestVariables: VisitorJobSearchV1Request!) {
    search {
      universalSearchNuxt {
        visitorJobSearchV1(request: $requestVariables) {
          paging {
            total
            offset
            count
          }
          results {
            id
            title
            description
            ontologySkills {
              uid
              prefLabel
              prettyName: prefLabel
              highlighted
            }
            jobTile {
              job {
                id
                ciphertext: cipherText
                jobType
                weeklyRetainerBudget
                hourlyBudgetMax
                hourlyBudgetMin
                hourlyEngagementType
                contractorTier
                createTime
                publishTime
                hourlyEngagementDuration {
                  label
                  weeks
                }
                fixedPriceAmount {
                  amount
                }
                fixedPriceEngagementDuration {
                  label
                  weeks
                }
              }
            }
          }
        }
      }
    }
  }
"""

# ---------------------------------------------------------------------------
# Job Details GraphQL Query (Phase 2)
# ---------------------------------------------------------------------------
# This second query fetches FULL job details for a single job by its ciphertext
# ID. It returns the complete description, client info, proposal count, etc.
# Captured from DevTools: /api/graphql/v1?alias=gql-query-get-visitor-job-details
JOB_DETAILS_QUERY = """
query JobPubDetailsQuery($id: ID!) {
  jobPubDetails(id: $id) {
    opening {
      description
      contractorTier
      workload
      clientActivity {
        totalApplicants
      }
      engagementDuration {
        label
      }
      annotations {
        customFields
      }
    }
    buyer {
      company {
        contractDate
      }
      location {
        country
      }
      stats {
        totalAssignments
        totalJobsWithHires
        totalCharges {
          amount
        }
      }
    }
    buyerExtra {
      isPaymentMethodVerified
    }
  }
}
"""
