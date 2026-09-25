"""
upwork package — Upwork freelance job scraping, filtering, and Discord alerts.
"""

from upwork.config import (
    TRACKED_QUERIES,
    TRACKED_URLS,
    CHANNEL_NAME,
    CHANNEL_ID,
    POLL_INTERVAL_SECONDS,
)
from upwork.scraper import UpworkScraper, parse_job
from upwork.auth_manager import AuthManager, SessionExpiredError
from upwork.poller import UpworkPoller
from upwork.formatter import format_job_message, format_thread_details, build_job_url


async def setup_upwork(bot, scraper: UpworkScraper = None, auth_manager: AuthManager = None):
    """Convenience helper to register Upwork poller cog and commands cog onto a Discord bot."""
    from upwork.commands import UpworkCommands
    from upwork.poller import UpworkPoller

    scraper_instance = scraper or UpworkScraper()
    auth_instance = auth_manager or AuthManager()

    await bot.add_cog(UpworkCommands(bot))
    await bot.add_cog(UpworkPoller(bot, scraper_instance, auth_instance))


__all__ = [
    "UpworkScraper",
    "AuthManager",
    "SessionExpiredError",
    "UpworkPoller",
    "format_job_message",
    "format_thread_details",
    "build_job_url",
    "parse_job",
    "setup_upwork",
    "TRACKED_QUERIES",
    "TRACKED_URLS",
    "CHANNEL_NAME",
    "CHANNEL_ID",
    "POLL_INTERVAL_SECONDS",
]
