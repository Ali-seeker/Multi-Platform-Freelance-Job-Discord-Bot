"""
facebook/config.py — Configuration loader and constants for the Facebook platform.
"""

import os
import json
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
    logger.warning(f"Could not load facebook/config.json: {e}. Using defaults.")
    _config_data = {
        "channel_name": "facebook",
        "channel_id": "",
        "tracked_queries": [
            {
                "query": "all",
                "label": "All Posts",
            }
        ],
        "tracked_groups": [],
        "fetch_interval": 15,
        "email_host": "imap.gmail.com",
        "email_port": 993,
        "email_folder": "INBOX",
        "mark_as_read": True,
    }

CHANNEL_NAME = _config_data.get("channel_name", "facebook")
CHANNEL_ID = _config_data.get("channel_id", "")
POLL_INTERVAL_SECONDS = _config_data.get("fetch_interval", 15)

# Facebook Session Cookies for Direct HTTP Scraper (Method 1)
FB_C_USER = os.getenv("FB_C_USER", "").strip()
FB_XS = os.getenv("FB_XS", "").strip()
FB_COOKIES = os.getenv("FB_COOKIES", "").strip()

# Email Connection Settings (Optional / Alternative)
FB_EMAIL_USER = os.getenv("FB_EMAIL_USER", os.getenv("FB_EMAIL_ACCOUNT", "")).strip()
FB_EMAIL_PASSWORD = os.getenv("FB_EMAIL_PASSWORD", os.getenv("FB_EMAIL_APP_PASSWORD", "")).strip()
FB_EMAIL_HOST = os.getenv("FB_EMAIL_HOST", _config_data.get("email_host", "imap.gmail.com")).strip()
FB_EMAIL_PORT = int(os.getenv("FB_EMAIL_PORT", _config_data.get("email_port", 993)))
FB_EMAIL_FOLDER = os.getenv("FB_EMAIL_FOLDER", _config_data.get("email_folder", "INBOX")).strip()
MARK_AS_READ = _config_data.get("mark_as_read", True)

raw_queries = _config_data.get("tracked_queries", [])
TRACKED_QUERIES = []
for entry in raw_queries:
    if isinstance(entry, str):
        TRACKED_QUERIES.append({"query": entry, "label": entry})
    elif isinstance(entry, dict):
        query = entry.get("query", "all")
        label = entry.get("label", query or "All Posts")
        TRACKED_QUERIES.append({"query": query, "label": label})

TRACKED_GROUPS = _config_data.get("tracked_groups", [])


def save_config() -> None:
    """Save the in-memory config back to facebook/config.json."""
    _config_data["channel_name"] = CHANNEL_NAME
    _config_data["channel_id"] = CHANNEL_ID
    _config_data["tracked_queries"] = TRACKED_QUERIES
    _config_data["tracked_groups"] = TRACKED_GROUPS
    _config_data["fetch_interval"] = POLL_INTERVAL_SECONDS
    _config_data["email_host"] = FB_EMAIL_HOST
    _config_data["email_port"] = FB_EMAIL_PORT
    _config_data["email_folder"] = FB_EMAIL_FOLDER
    _config_data["mark_as_read"] = MARK_AS_READ
    try:
        with open(CONFIG_JSON_PATH, "w") as f:
            json.dump(_config_data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not save facebook/config.json: {e}")


def set_channel_id(new_id: str) -> None:
    """Persist the resolved or created Facebook Discord channel ID."""
    global CHANNEL_ID
    CHANNEL_ID = str(new_id)
    save_config()
    logger.info(f"💾 Saved Facebook channel ID ({CHANNEL_ID}) to facebook/config.json")


def add_new_tracker(keyword: str, label: str = ""):
    """Adds a new query/keyword filter to Facebook post tracking."""
    if not label:
        label = keyword

    for item in TRACKED_QUERIES:
        if item.get("label", "").lower() == label.lower():
            logger.info(f"Query '{label}' is already tracked on Facebook.")
            return item

    new_entry = {"query": keyword, "label": label}
    TRACKED_QUERIES.append(new_entry)
    save_config()
    logger.info(f"💾 Added new query to Facebook tracking: {label}")
    return new_entry


def remove_tracker_by_label(label: str):
    """Removes a query filter from Facebook tracking by label."""
    for i, entry in enumerate(TRACKED_QUERIES):
        if entry.get("label", "").lower() == label.lower():
            removed = TRACKED_QUERIES.pop(i)
            save_config()
            logger.info(f"🗑️ Removed query from Facebook tracking: {label}")
            return removed
    return None
