"""
guru package — Guru freelance job scraping and Discord alerts.
"""

from guru.config import (
    TRACKED_QUERIES,
    CHANNEL_NAME,
    CHANNEL_ID,
    POLL_INTERVAL_SECONDS,
)
from guru.scraper import GuruScraper
from guru.poller import GuruPoller
from guru.formatter import format_guru_job_message, format_guru_thread_details


async def setup_guru(bot, scraper: GuruScraper = None):
    """Convenience helper to register Guru poller cog and commands cog onto a Discord bot."""
    from guru.commands import GuruCommands
    from guru.poller import GuruPoller

    scraper_instance = scraper or GuruScraper()

    await bot.add_cog(GuruCommands(bot))
    await bot.add_cog(GuruPoller(bot, scraper_instance))


__all__ = [
    "GuruScraper",
    "GuruPoller",
    "format_guru_job_message",
    "format_guru_thread_details",
    "setup_guru",
    "TRACKED_QUERIES",
    "CHANNEL_NAME",
    "CHANNEL_ID",
    "POLL_INTERVAL_SECONDS",
]
