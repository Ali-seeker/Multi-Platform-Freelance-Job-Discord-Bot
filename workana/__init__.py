"""
workana package — Workana freelance project scraping and Discord alerts.
"""

from .config import (
    TRACKED_QUERIES,
    CHANNEL_NAME,
    CHANNEL_ID,
    POLL_INTERVAL_SECONDS,
)
from .scraper import WorkanaScraper
from .poller import WorkanaPoller
from .formatter import format_workana_job_message, format_workana_thread_details


async def setup_workana(bot, scraper: WorkanaScraper = None):
    """Convenience helper to register Workana poller cog and commands cog onto a Discord bot."""
    from .commands import WorkanaCommands
    from .poller import WorkanaPoller

    scraper_instance = scraper or WorkanaScraper()

    await bot.add_cog(WorkanaCommands(bot))
    await bot.add_cog(WorkanaPoller(bot, scraper_instance))


__all__ = [
    "WorkanaScraper",
    "WorkanaPoller",
    "format_workana_job_message",
    "format_workana_thread_details",
    "setup_workana",
    "TRACKED_QUERIES",
    "CHANNEL_NAME",
    "CHANNEL_ID",
    "POLL_INTERVAL_SECONDS",
]
