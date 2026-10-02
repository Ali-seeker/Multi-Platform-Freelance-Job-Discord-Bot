"""
threads/config.py — Configuration loader and query constants for the Threads platform.
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
    logger.warning(f"Could not load threads/config.json: {e}. Using defaults.")
    _config_data = {
        "channel_name": "threads",
        "channel_id": "",
        "tracked_queries": [
            {
                "query": "hiring developer",
                "label": "Hiring Developer",
            }
        ],
        "fetch_interval": 300,
        "jobs_per_page": 20,
    }

CHANNEL_NAME = _config_data.get("channel_name", "threads")
CHANNEL_ID = _config_data.get("channel_id", "")
POLL_INTERVAL_SECONDS = _config_data.get("fetch_interval", 300)
JOBS_PER_PAGE = int(_config_data.get("jobs_per_page", os.getenv("THREADS_JOBS_PER_PAGE", "20")))

# Optional Threads session cookie (if user desires authenticated search)
THREADS_SESSION_ID = os.getenv("THREADS_SESSION_ID", "").strip()

raw_queries = _config_data.get("tracked_queries", [])
TRACKED_QUERIES = []
for entry in raw_queries:
    if isinstance(entry, str):
        encoded = urllib.parse.quote_plus(entry)
        url = f"https://www.threads.net/search?q={encoded}&serp_type=default&filter=recent"
        TRACKED_QUERIES.append({"query": entry, "url": url, "label": entry})
    elif isinstance(entry, dict):
        query = entry.get("query", "")
        url = entry.get("url", "")
        label = entry.get("label", "")
        if not query and url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            query = qs.get("q", [""])[0] or label
        if not label:
            label = query or "Threads"
        if not url and query:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.threads.net/search?q={encoded}&serp_type=default&filter=recent"
        TRACKED_QUERIES.append({"query": query, "url": url, "label": label})


def save_config() -> None:
    """Save the in-memory config back to threads/config.json."""
    _config_data["channel_name"] = CHANNEL_NAME
    _config_data["channel_id"] = CHANNEL_ID
    _config_data["tracked_queries"] = TRACKED_QUERIES
    _config_data["fetch_interval"] = POLL_INTERVAL_SECONDS
    _config_data["jobs_per_page"] = JOBS_PER_PAGE
    try:
        with open(CONFIG_JSON_PATH, "w") as f:
            json.dump(_config_data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not save threads/config.json: {e}")


def set_channel_id(new_id: str) -> None:
    """Persist the resolved or created Threads Discord channel ID."""
    global CHANNEL_ID
    CHANNEL_ID = str(new_id)
    save_config()
    logger.info(f"💾 Saved Threads channel ID ({CHANNEL_ID}) to threads/config.json")


def add_new_tracker(keyword_or_url: str, label: str = ""):
    """Adds a new search query to Threads tracking. All posts route to #threads."""
    parsed_query = keyword_or_url
    if "threads.net" in keyword_or_url:
        parsed = urllib.parse.urlparse(keyword_or_url)
        qs = urllib.parse.parse_qs(parsed.query)
        parsed_query = qs.get("q", [""])[0] or label

    if not label:
        label = parsed_query

    encoded = urllib.parse.quote_plus(parsed_query)
    threads_url = f"https://www.threads.net/search?q={encoded}&serp_type=default&filter=recent"

    for item in TRACKED_QUERIES:
        if item.get("label", "").lower() == label.lower():
            logger.info(f"Query '{label}' is already tracked on Threads.")
            return item

    new_entry = {"query": parsed_query, "url": threads_url, "label": label}
    TRACKED_QUERIES.append(new_entry)
    save_config()
    logger.info(f"💾 Added new query to Threads tracking: {label}")
    return new_entry


def remove_tracker_by_label(label: str):
    """Removes a query from Threads tracking by label."""
    for i, entry in enumerate(TRACKED_QUERIES):
        if entry.get("label", "").lower() == label.lower():
            removed = TRACKED_QUERIES.pop(i)
            save_config()
            logger.info(f"🗑️ Removed query from Threads tracking: {label}")
            return removed
    return None
