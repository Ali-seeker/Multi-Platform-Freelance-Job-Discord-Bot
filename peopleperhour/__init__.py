"""
peopleperhour package — PeoplePerHour platform integration for freelance job monitoring.
"""

from peopleperhour.scraper import PeoplePerHourScraper
from peopleperhour.poller import PeoplePerHourPoller
from peopleperhour.commands import PeoplePerHourCommands


async def setup_peopleperhour(bot, scraper: PeoplePerHourScraper = None):
    """
    Setup helper to attach PeoplePerHour cogs to the Discord bot.
    """
    await bot.add_cog(PeoplePerHourCommands(bot))
    await bot.add_cog(PeoplePerHourPoller(bot, scraper=scraper))
