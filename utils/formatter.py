"""
utils/formatter.py — Backward-compatible message formatter shim.
Re-exports Upwork message formatting from upwork.formatter and shared Discord helpers.
"""

from upwork.formatter import (
    format_job_message,
    format_thread_details,
    build_job_url,
)
from utils.discord_helpers import (
    split_message,
    format_relative_time,
)

__all__ = [
    "format_job_message",
    "format_thread_details",
    "build_job_url",
    "split_message",
    "format_relative_time",
]
