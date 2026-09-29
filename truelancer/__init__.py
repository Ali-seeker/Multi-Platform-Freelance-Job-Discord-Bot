"""
truelancer package — Truelancer platform integration for freelance job monitoring.
"""

from truelancer.scraper import TruelancerScraper
from truelancer.poller import TruelancerPoller
from truelancer.commands import TruelancerCommands


async def setup_truelancer(bot, scraper: TruelancerScraper = None):
    """
    Setup helper to attach Truelancer cogs to the Discord bot.
    """
    await bot.add_cog(TruelancerCommands(bot))
    await bot.add_cog(TruelancerPoller(bot, scraper=scraper))
