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
    POLL_INTERVAL_SECONDS = _config_data.get("fetch_interval", int(os.getenv("POLL_INTERVAL_SECONDS", "10")))
except Exception as e:
    logger.error(f"Could not load config.json: {e}")
    TRACKED_URLS = []
    POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))

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
            return part[len(cookie_name) + 1:]
    return ""


# Extract the XSRF token from cookies — Upwork requires it as a header
# for CSRF protection. Without it, you get 403 Forbidden.
_xsrf_token = _extract_cookie_value(COOKIES, "XSRF-TOKEN")

# Extract visitor ID from cookies for the tracing header
_visitor_id = _extract_cookie_value(COOKIES, "visitor_id")

# Headers that mimic a real browser request.
# The cookie and authorization values are injected from .env at runtime.
REQUEST_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "authorization": BEARER_TOKEN,
    "content-type": "application/json",
    "origin": "https://www.upwork.com",
    "referer": "https://www.upwork.com/nx/search/jobs/",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "x-upwork-accept-language": "en-US",
    # CSRF protection — must match the XSRF-TOKEN cookie value
    "x-odesk-csrf-token": _xsrf_token,
    # Visitor tracking headers from the original request
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
  fragment JobPubOpeningInfoFragment on Job {
    ciphertext
    id
    type
    access
    title
    hideBudget
    createdOn
    notSureProjectDuration
    notSureFreelancersToHire
    notSureExperienceLevel
    notSureLocationPreference
    premium
  }
  fragment JobPubOpeningSegmentationDataFragment on JobSegmentation {
    customValue
    label
    name
    sortOrder
    type
    value
    skill {
      description
      externalLink
      prettyName
      skill
      id
    }
  }
  fragment JobPubOpeningSandDataFragment on SandsData {
    occupation {
      freeText
      ontologyId
      prefLabel
      id
      uid: id
    }
    ontologySkills {
      groupId
      id
      freeText
      prefLabel
      groupPrefLabel
      relevance
    }
    additionalSkills {
      groupId
      id
      freeText
      prefLabel
      relevance
    }
  }
  fragment JobPubOpeningFragment on JobPubOpeningInfo {
    status
    postedOn
    publishTime
    sourcingTime
    startDate
    deliveryDate
    workload
    contractorTier
    description
    info {
      ...JobPubOpeningInfoFragment
    }
    segmentationData {
      ...JobPubOpeningSegmentationDataFragment
    }
    sandsData {
      ...JobPubOpeningSandDataFragment
    }
    category {
      name
      urlSlug
    }
    categoryGroup {
      name
      urlSlug
    }
    budget {
      amount
      currencyCode
    }
    annotations {
      customFields
      tags
    }
    engagementDuration {
      label
      weeks
    }
    extendedBudgetInfo {
      hourlyBudgetMin
      hourlyBudgetMax
      hourlyBudgetType
    }
    clientActivity {
      lastBuyerActivity
      totalApplicants
      totalHired
      totalInvitedToInterview
      unansweredInvites
      invitationsSent
      numberOfPositionsToHire
    }
    deliverables
    deadline
    tools {
      name
    }
  }
  fragment JobPubBuyerInfoFragment on JobPubBuyerInfo {
    location {
      offsetFromUtcMillis
      countryTimezone
      city
      country
    }
    stats {
      totalAssignments
      activeAssignmentsCount
      hoursCount
      feedbackCount
      score
      totalJobsWithHires
      totalCharges {
        amount
      }
    }
    company {
      name @include(if: $isLoggedIn)
      companyId @include(if: $isLoggedIn)
      isEDCReplicated
      contractDate
      profile {
        industry
        size
      }
    }
    jobs {
      openCount @include(if: $isLoggedIn)
      postedCount @include(if: $isLoggedIn)
      openJobs @include(if: $isLoggedIn) {
        id
        uid: id
        isPtcPrivate
        ciphertext
        title
        type
      }
    }
    avgHourlyJobsRate @include(if: $isLoggedIn) {
      amount
    }
  }
  fragment JobQualificationsFragment on JobQualifications {
    countries
    earnings
    groupRecno
    languages
    localDescription
    localFlexibilityDescription
    localMarket
    minJobSuccessScore
    minOdeskHours
    onSiteType
    prefEnglishSkill
    regions
    risingTalent
    shouldHavePortfolio
    states
    tests
    timezones
    type
    locationCheckRequired
    group {
      groupId
      groupLogo
      groupName
    }
    location {
      city
      country
      countryTimezone
      offsetFromUtcMillis
      state
      worldRegion
    }
    locations {
      id
      type
    }
    minHoursWeek @skip(if: $isLoggedIn)
    readyToStartToday {
      expiresAt
    }
  }
  query JobPubDetailsQuery($id: ID!, $isLoggedIn: Boolean!) {
    jobPubDetails(id: $id) {
      opening {
        ...JobPubOpeningFragment
      }
      qualifications {
        ...JobQualificationsFragment
      }
      buyer {
        ...JobPubBuyerInfoFragment
      }
      buyerExtra {
        isPaymentMethodVerified
      }
    }
  }
"""

