"""
freelancer/config.py — Configuration loader and query constants for the Freelancer.com platform.
"""

import os
import json
import urllib.parse
from dotenv import load_dotenv

from logger import get_logger

logger = get_logger(__name__)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(ROOT_DIR, ".env"))

CONFIG_JSON_PATH = os.path.join(os.path.dirname(__file__), "config.json")

try:
    with open(CONFIG_JSON_PATH, "r") as f:
        _config_data = json.load(f)
except Exception as e:
    logger.warning(f"Could not load freelancer/config.json: {e}. Using defaults.")
    _config_data = {
        "channel_name": "freelancer",
        "channel_id": "",
        "tracked_queries": [
            {
                "query": "automation",
                "url": "https://www.freelancer.com/jobs/?keyword=automation",
                "label": "Automation",
            }
        ],
        "fetch_interval": 15,
        "jobs_per_page": 20,
    }

CHANNEL_NAME = _config_data.get("channel_name", "freelancer")
CHANNEL_ID = _config_data.get("channel_id", "")
POLL_INTERVAL_SECONDS = _config_data.get("fetch_interval", 15)
JOBS_PER_PAGE = int(_config_data.get("jobs_per_page", os.getenv("FREELANCER_JOBS_PER_PAGE", "20")))

raw_queries = _config_data.get("tracked_queries", [])
TRACKED_QUERIES = []
for entry in raw_queries:
    if isinstance(entry, str):
        encoded = urllib.parse.quote(entry)
        url = f"https://www.freelancer.com/jobs/?keyword={encoded}"
        TRACKED_QUERIES.append({"query": entry, "url": url, "label": entry})
    elif isinstance(entry, dict):
        query = entry.get("query", "")
        url = entry.get("url", "")
        label = entry.get("label", "")
        if not query and url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            query = qs.get("keyword", [""])[0] or qs.get("q", [""])[0] or label
        if not label:
            label = query or "Freelancer"
        if not url and query:
            encoded = urllib.parse.quote(query)
            url = f"https://www.freelancer.com/jobs/?keyword={encoded}"
        TRACKED_QUERIES.append({"query": query, "url": url, "label": label})


def save_config() -> None:
    """Save the in-memory config back to freelancer/config.json."""
    _config_data["channel_name"] = CHANNEL_NAME
    _config_data["channel_id"] = CHANNEL_ID
    _config_data["tracked_queries"] = TRACKED_QUERIES
    _config_data["fetch_interval"] = POLL_INTERVAL_SECONDS
    _config_data["jobs_per_page"] = JOBS_PER_PAGE
    try:
        with open(CONFIG_JSON_PATH, "w") as f:
            json.dump(_config_data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not save freelancer/config.json: {e}")


def set_channel_id(new_id: str) -> None:
    """Persist the resolved or created Freelancer Discord channel ID."""
    global CHANNEL_ID
    CHANNEL_ID = str(new_id)
    save_config()
    logger.info(f"💾 Saved Freelancer channel ID ({CHANNEL_ID}) to freelancer/config.json")


def add_new_tracker(keyword_or_url: str, label: str = ""):
    """Adds a new query to Freelancer tracking. All jobs route to #freelancer."""
    parsed_query = keyword_or_url
    if "freelancer.com" in keyword_or_url:
        parsed = urllib.parse.urlparse(keyword_or_url)
        qs = urllib.parse.parse_qs(parsed.query)
        parsed_query = qs.get("keyword", [""])[0] or qs.get("q", [""])[0] or label

    if not label:
        label = parsed_query

    encoded = urllib.parse.quote(parsed_query)
    fl_url = f"https://www.freelancer.com/jobs/?keyword={encoded}"

    for item in TRACKED_QUERIES:
        if item.get("label", "").lower() == label.lower():
            logger.info(f"Query '{label}' is already tracked on Freelancer.")
            return item

    new_entry = {"query": parsed_query, "url": fl_url, "label": label}
    TRACKED_QUERIES.append(new_entry)
    save_config()
    logger.info(f"💾 Added new query to Freelancer tracking: {label}")
    return new_entry


def remove_tracker_by_label(label: str):
    """Removes a query from Freelancer tracking by label."""
    for i, entry in enumerate(TRACKED_QUERIES):
        if entry.get("label", "").lower() == label.lower():
            removed = TRACKED_QUERIES.pop(i)
            save_config()
            logger.info(f"🗑️ Removed query from Freelancer tracking: {label}")
            return removed
    return None
