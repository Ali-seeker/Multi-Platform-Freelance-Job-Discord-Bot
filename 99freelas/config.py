"""
99freelas/config.py — Configuration loader and query constants for the 99freelas platform.
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
    with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
        _config_data = json.load(f)
except Exception as e:
    logger.warning(f"Could not load 99freelas/config.json: {e}. Using defaults.")
    _config_data = {
        "channel_name": "99freelas",
        "channel_id": "",
        "tracked_queries": [
            {
                "query": "automation",
                "url": "https://www.99freelas.com.br/projects?q=automation",
                "label": "Automation",
            },
            {
                "query": "python",
                "url": "https://www.99freelas.com.br/projects?q=python",
                "label": "Python",
            },
        ],
        "fetch_interval": 30,
        "jobs_per_page": 20,
    }

CHANNEL_NAME = _config_data.get("channel_name", "99freelas")
CHANNEL_ID = _config_data.get("channel_id", "")
POLL_INTERVAL_SECONDS = _config_data.get("fetch_interval", 30)
JOBS_PER_PAGE = int(_config_data.get("jobs_per_page", os.getenv("FREELAS99_JOBS_PER_PAGE", "20")))

raw_queries = _config_data.get("tracked_queries", [])
TRACKED_QUERIES = []
for entry in raw_queries:
    if isinstance(entry, str):
        encoded = urllib.parse.quote(entry)
        url = f"https://www.99freelas.com.br/projects?q={encoded}"
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
            label = query or "99freelas"
        if not url and query:
            encoded = urllib.parse.quote(query)
            url = f"https://www.99freelas.com.br/projects?q={encoded}"
        TRACKED_QUERIES.append({"query": query, "url": url, "label": label})


def save_config() -> None:
    """Save the in-memory config back to 99freelas/config.json."""
    _config_data["channel_name"] = CHANNEL_NAME
    _config_data["channel_id"] = CHANNEL_ID
    _config_data["tracked_queries"] = TRACKED_QUERIES
    _config_data["fetch_interval"] = POLL_INTERVAL_SECONDS
    _config_data["jobs_per_page"] = JOBS_PER_PAGE
    try:
        with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(_config_data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not save 99freelas/config.json: {e}")


def set_channel_id(new_id: str) -> None:
    """Persist the resolved or created 99freelas Discord channel ID."""
    global CHANNEL_ID
    CHANNEL_ID = str(new_id)
    save_config()
    logger.info(f"💾 Saved 99freelas channel ID ({CHANNEL_ID}) to 99freelas/config.json")


def add_new_tracker(keyword_or_url: str, label: str = ""):
    """Adds a new query to 99freelas tracking. All jobs route to #99freelas."""
    parsed_query = keyword_or_url
    if "99freelas.com.br" in keyword_or_url:
        parsed = urllib.parse.urlparse(keyword_or_url)
        qs = urllib.parse.parse_qs(parsed.query)
        parsed_query = qs.get("q", [""])[0] or label

    if not label:
        label = parsed_query

    encoded = urllib.parse.quote(parsed_query)
    freelas_url = f"https://www.99freelas.com.br/projects?q={encoded}"

    for item in TRACKED_QUERIES:
        if item.get("label", "").lower() == label.lower():
            logger.info(f"Query '{label}' is already tracked on 99freelas.")
            return item

    new_entry = {"query": parsed_query, "url": freelas_url, "label": label}
    TRACKED_QUERIES.append(new_entry)
    save_config()
    logger.info(f"💾 Added new query to 99freelas tracking: {label}")
    return new_entry


def remove_tracker_by_label(label: str):
    """Removes a query from 99freelas tracking by label."""
    for i, entry in enumerate(TRACKED_QUERIES):
        if entry.get("label", "").lower() == label.lower():
            removed = TRACKED_QUERIES.pop(i)
            save_config()
            logger.info(f"🗑️ Removed query from 99freelas tracking: {label}")
            return removed
    return None
