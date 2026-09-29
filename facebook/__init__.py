"""
facebook package — Facebook platform integration for group post monitoring via email notifications.
"""

from facebook.email_listener import FacebookEmailListener
from facebook.poller import FacebookPoller
from facebook.commands import FacebookCommands


async def setup_facebook(bot, listener: FacebookEmailListener = None):
    """
    Setup helper to attach Facebook cogs to the Discord bot.
    """
    await bot.add_cog(FacebookCommands(bot))
    await bot.add_cog(FacebookPoller(bot, listener=listener))
