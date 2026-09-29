"""
99freelas package — 99freelas freelance project scraping and Discord alerts.
"""

from .config import (
    TRACKED_QUERIES,
    CHANNEL_NAME,
    CHANNEL_ID,
    POLL_INTERVAL_SECONDS,
)
from .scraper import Freelance99Scraper
from .poller import Freelance99Poller
from .formatter import format_99freelas_job_message, format_99freelas_thread_details


async def setup_99freelas(bot, scraper: Freelance99Scraper = None):
    """Convenience helper to register 99freelas poller cog and commands cog onto a Discord bot."""
    from .commands import Freelance99Commands
    from .poller import Freelance99Poller

    scraper_instance = scraper or Freelance99Scraper()

    await bot.add_cog(Freelance99Commands(bot))
    await bot.add_cog(Freelance99Poller(bot, scraper_instance))


__all__ = [
    "Freelance99Scraper",
    "Freelance99Poller",
    "format_99freelas_job_message",
    "format_99freelas_thread_details",
    "setup_99freelas",
    "TRACKED_QUERIES",
    "CHANNEL_NAME",
    "CHANNEL_ID",
    "POLL_INTERVAL_SECONDS",
]
