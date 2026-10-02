"""
workana/config.py — Configuration loader and query constants for the Workana platform.
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
    logger.warning(f"Could not load workana/config.json: {e}. Using defaults.")
    _config_data = {
        "channel_name": "workana",
        "channel_id": "",
        "tracked_queries": [
            {
                "query": "Python",
                "url": "https://www.workana.com/jobs?query=Python&format=json",
                "label": "Python",
            },
            {
                "query": "React",
                "url": "https://www.workana.com/jobs?query=React&format=json",
                "label": "React",
            },
        ],
        "fetch_interval": 300,
        "jobs_per_page": 15,
    }

CHANNEL_NAME = _config_data.get("channel_name", "workana")
CHANNEL_ID = _config_data.get("channel_id", "")
POLL_INTERVAL_SECONDS = _config_data.get("fetch_interval", 300)
JOBS_PER_PAGE = int(_config_data.get("jobs_per_page", os.getenv("WORKANA_JOBS_PER_PAGE", "15")))

raw_queries = _config_data.get("tracked_queries", [])
TRACKED_QUERIES = []
for entry in raw_queries:
    if isinstance(entry, str):
        encoded = urllib.parse.quote_plus(entry)
        url = f"https://www.workana.com/jobs?query={encoded}&format=json"
        TRACKED_QUERIES.append({"query": entry, "url": url, "label": entry})
    elif isinstance(entry, dict):
        query = entry.get("query", "")
        url = entry.get("url", "")
        label = entry.get("label", "")
        if not query and url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            query = qs.get("query", [""])[0]
        if not url and query:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.workana.com/jobs?query={encoded}&format=json"
        if not label:
            label = query or "Workana Jobs"
        TRACKED_QUERIES.append({"query": query, "url": url, "label": label})


def save_config(channel_id: str | None = None, tracked_queries: list | None = None) -> None:
    """Persists updated configuration back to workana/config.json."""
    if channel_id is not None:
        _config_data["channel_id"] = str(channel_id)
    if tracked_queries is not None:
        _config_data["tracked_queries"] = tracked_queries

    try:
        with open(CONFIG_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(_config_data, f, indent=4)
        logger.info("Saved updated workana/config.json")
    except Exception as e:
        logger.error(f"Failed to save workana/config.json: {e}")


def set_channel_id(channel_id: int | str) -> None:
    """Updates the dedicated Workana channel ID in memory and in config.json."""
    global CHANNEL_ID
    CHANNEL_ID = str(channel_id)
    save_config(channel_id=CHANNEL_ID)


def add_new_tracker(query: str, label: str) -> None:
    """Adds a new search query tracker to Workana configuration."""
    global TRACKED_QUERIES
    for existing in TRACKED_QUERIES:
        if existing["label"].lower() == label.lower():
            raise ValueError(f"A tracker with label '{label}' already exists.")

    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.workana.com/jobs?query={encoded}&format=json"
    new_entry = {"query": query, "url": url, "label": label}
    TRACKED_QUERIES.append(new_entry)
    save_config(tracked_queries=TRACKED_QUERIES)


def remove_tracker_by_label(label: str) -> bool:
    """Removes a search query tracker by its label."""
    global TRACKED_QUERIES
    original_len = len(TRACKED_QUERIES)
    TRACKED_QUERIES = [q for q in TRACKED_QUERIES if q["label"].lower() != label.lower()]
    if len(TRACKED_QUERIES) < original_len:
        save_config(tracked_queries=TRACKED_QUERIES)
        return True
    return False
