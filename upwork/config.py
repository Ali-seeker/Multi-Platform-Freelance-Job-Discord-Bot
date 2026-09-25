"""
upwork/config.py — Upwork-specific configuration loader and query constants.
"""

import os
import sys
import json
import urllib.parse
from dotenv import load_dotenv

from logger import get_logger

logger = get_logger(__name__)

# Load .env file from the project root
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(ROOT_DIR, ".env"))


def _require_env(key: str) -> str:
    """Get an environment variable or exit with a helpful error."""
    value = os.getenv(key)
    if not value:
        logger.error(f"Missing required environment variable: {key}")
        logger.error("   -> Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    return value


# --- Authentication --------------------------------------------------------
BEARER_TOKEN = _require_env("UPWORK_BEARER_TOKEN")
COOKIES = _require_env("UPWORK_COOKIES")

# --- Search Tuning ---------------------------------------------------------
JOBS_PER_PAGE = int(os.getenv("UPWORK_JOBS_PER_PAGE", "10"))

# --- Upwork Config JSON ----------------------------------------------------
CONFIG_JSON_PATH = os.path.join(os.path.dirname(__file__), "config.json")
ROOT_CONFIG_JSON_PATH = os.path.join(ROOT_DIR, "config.json")

# Load configuration, giving priority to whichever was more recently modified or root
_config_data = {}
for p in [CONFIG_JSON_PATH, ROOT_CONFIG_JSON_PATH]:
    if os.path.exists(p):
        try:
            with open(p, "r") as f:
                loaded = json.load(f)
                if loaded:
                    # Update with non-empty values
                    for k, v in loaded.items():
                        if v or k not in _config_data:
                            _config_data[k] = v
        except Exception as e:
            logger.warning(f"Could not load {p}: {e}")

if not _config_data:
    _config_data = {
        "channel_name": "upwork",
        "channel_id": "",
        "tracked_queries": [],
        "fetch_interval": int(os.getenv("POLL_INTERVAL_SECONDS", "10")),
    }

CHANNEL_NAME = _config_data.get("channel_name", "upwork")
CHANNEL_ID = _config_data.get("channel_id", "")
POLL_INTERVAL_SECONDS = _config_data.get(
    "fetch_interval", int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
)
JOBS_PER_PAGE = int(
    _config_data.get("jobs_per_page", os.getenv("UPWORK_JOBS_PER_PAGE", "10"))
)

# Normalize tracked_queries / tracked_urls
raw_queries = _config_data.get("tracked_queries", [])
if not raw_queries and "tracked_urls" in _config_data:
    raw_queries = _config_data.get("tracked_urls", [])

TRACKED_QUERIES = []
for entry in raw_queries:
    if isinstance(entry, str):
        encoded = urllib.parse.quote(entry)
        url = f"https://www.upwork.com/nx/search/jobs/?q={encoded}&sort=recency"
        TRACKED_QUERIES.append({"query": entry, "url": url, "label": entry})
    elif isinstance(entry, dict):
        query = entry.get("query")
        url = entry.get("url", "")
        label = entry.get("label", "")
        if not query and url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            query = qs.get("q", [""])[0] or label
        if not label:
            label = query or "Upwork"
        if not url and query:
            encoded = urllib.parse.quote(query)
            url = f"https://www.upwork.com/nx/search/jobs/?q={encoded}&sort=recency"
        TRACKED_QUERIES.append({"query": query, "url": url, "label": label})

# Backward compatibility alias
TRACKED_URLS = TRACKED_QUERIES


def save_config() -> None:
    """Save the in-memory config back to both upwork/config.json and root config.json."""
    _config_data["channel_name"] = CHANNEL_NAME
    _config_data["channel_id"] = CHANNEL_ID
    _config_data["tracked_queries"] = TRACKED_QUERIES
    _config_data["fetch_interval"] = POLL_INTERVAL_SECONDS
    _config_data["jobs_per_page"] = JOBS_PER_PAGE
    for p in [CONFIG_JSON_PATH, ROOT_CONFIG_JSON_PATH]:
        try:
            with open(p, "w") as f:
                json.dump(_config_data, f, indent=4)
        except Exception as e:
            logger.warning(f"Could not save config to {p}: {e}")


def set_channel_id(new_id: str) -> None:
    """Persists the resolved or created Upwork channel ID."""
    global CHANNEL_ID
    CHANNEL_ID = str(new_id)
    save_config()
    logger.info(f"💾 Saved Upwork channel ID ({CHANNEL_ID}) to upwork/config.json")


def add_new_tracker(keyword_or_url: str, label: str = "", channel_id: str = ""):
    """Adds a new search query to Upwork tracking. All jobs go to single #upwork channel."""
    parsed_query = keyword_or_url
    if "upwork.com" in keyword_or_url:
        parsed = urllib.parse.urlparse(keyword_or_url)
        qs = urllib.parse.parse_qs(parsed.query)
        parsed_query = qs.get("q", [""])[0] or label

    if not label:
        label = parsed_query

    encoded = urllib.parse.quote(parsed_query)
    upwork_url = f"https://www.upwork.com/nx/search/jobs/?q={encoded}&sort=recency"

    # Check for existing duplicate query
    for item in TRACKED_QUERIES:
        if item.get("label", "").lower() == label.lower():
            logger.info(f"Query '{label}' is already tracked.")
            return item

    new_entry = {"query": parsed_query, "url": upwork_url, "label": label}
    TRACKED_QUERIES.append(new_entry)
    save_config()
    logger.info(f"💾 Added new query to Upwork tracking: {label}")
    return new_entry


def remove_tracker_by_label(label: str):
    """Removes a query from Upwork tracking by label. Returns the removed entry if found."""
    for i, entry in enumerate(TRACKED_QUERIES):
        if entry.get("label", "").lower() == label.lower():
            removed = TRACKED_QUERIES.pop(i)
            save_config()
            logger.info(f"🗑️ Removed query from Upwork tracking: {label}")
            return removed
    return None


def update_tracker_by_label(old_label: str, new_label: str, new_url_or_query: str):
    """Updates a query's label/search in Upwork config."""
    for entry in TRACKED_QUERIES:
        if entry.get("label", "").lower() == old_label.lower():
            entry["label"] = new_label
            if "upwork.com" in new_url_or_query:
                entry["url"] = new_url_or_query
                parsed = urllib.parse.urlparse(new_url_or_query)
                entry["query"] = urllib.parse.parse_qs(parsed.query).get("q", [new_label])[0]
            else:
                entry["query"] = new_url_or_query
                encoded = urllib.parse.quote(new_url_or_query)
                entry["url"] = f"https://www.upwork.com/nx/search/jobs/?q={encoded}&sort=recency"
            save_config()
            logger.info(f"🔄 Updated Upwork tracker: {old_label} -> {new_label}")
            return entry
    return None


# --- Discord Globals -------------------------------------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = CHANNEL_ID or os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "")

# --- Upwork API Details ----------------------------------------------------
GRAPHQL_URL = "https://www.upwork.com/api/graphql/v1"


def _extract_cookie_value(cookie_string: str, cookie_name: str) -> str:
    """Extract a specific cookie's value from the raw cookie header string."""
    for part in cookie_string.split(";"):
        part = part.strip()
        if part.startswith(f"{cookie_name}="):
            return part[len(cookie_name) + 1 :]
    return ""


_xsrf_token = _extract_cookie_value(COOKIES, "XSRF-TOKEN")
_visitor_id = _extract_cookie_value(COOKIES, "visitor_id")

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
    attachments @include(if: $isLoggedIn) {
      fileName
      length
      uri
    }
    clientActivity @include(if: $isLoggedIn) {
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
  fragment JobPubSimilarJobsFragment on PubSimilarJob {
    id
    ciphertext
    title
    description
    engagement
    durationLabel
    contractorTier
    type
    createdOn
    renewedOn
    amount {
      amount
    }
    maxAmount {
      amount
    }
    ontologySkills {
      id
      prefLabel
    }
    hourlyBudgetMin
    hourlyBudgetMax
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
      similarJobs {
        ...JobPubSimilarJobsFragment
      }
      buyerExtra {
        isPaymentMethodVerified
      }
    }
  }
"""
