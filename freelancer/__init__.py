"""
freelancer package — Freelancer.com platform integration for freelance job monitoring.
"""

from freelancer.scraper import FreelancerScraper
from freelancer.poller import FreelancerPoller
from freelancer.commands import FreelancerCommands


async def setup_freelancer(bot, scraper: FreelancerScraper = None):
    """
    Setup helper to attach Freelancer.com cogs to the Discord bot.
    """
    await bot.add_cog(FreelancerCommands(bot))
    await bot.add_cog(FreelancerPoller(bot, scraper=scraper))
