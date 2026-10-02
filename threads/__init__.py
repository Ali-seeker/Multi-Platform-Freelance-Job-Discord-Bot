"""
threads package — Meta Threads (threads.net) post scraping and Discord alerts.
"""

from .config import (
    TRACKED_QUERIES,
    CHANNEL_NAME,
    CHANNEL_ID,
    POLL_INTERVAL_SECONDS,
)
from .scraper import ThreadsScraper
from .poller import ThreadsPoller
from .formatter import format_threads_job_message, format_threads_thread_details


async def setup_threads(bot, scraper: ThreadsScraper = None):
    """Convenience helper to register Threads poller cog and commands cog onto a Discord bot."""
    from .commands import ThreadsCommands
    from .poller import ThreadsPoller

    scraper_instance = scraper or ThreadsScraper()

    await bot.add_cog(ThreadsCommands(bot))
    await bot.add_cog(ThreadsPoller(bot, scraper_instance))


__all__ = [
    "ThreadsScraper",
    "ThreadsPoller",
    "format_threads_job_message",
    "format_threads_thread_details",
    "setup_threads",
    "TRACKED_QUERIES",
    "CHANNEL_NAME",
    "CHANNEL_ID",
    "POLL_INTERVAL_SECONDS",
]
