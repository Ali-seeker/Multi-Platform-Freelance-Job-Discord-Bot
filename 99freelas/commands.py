"""
99freelas/commands.py — Discord Slash Commands for managing 99freelas trackers.
"""

import discord
from discord.ext import commands
from discord import app_commands
from .config import (
    TRACKED_QUERIES,
    add_new_tracker,
    remove_tracker_by_label,
    CHANNEL_NAME,
)
from logger import get_logger

logger = get_logger(__name__)


class Freelance99Commands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="99freelas_add_tracker",
        description="Add a new search keyword for 99freelas (jobs will post to #99freelas)",
    )
    @app_commands.describe(keyword="The search term for 99freelas jobs (e.g. 'Automation', 'Python')")
    @app_commands.default_permissions(administrator=True)
    async def add_tracker(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = add_new_tracker(keyword)
            msg = (
                f"✅ **99freelas Tracker Added!**\n"
                f"• Keyword: `{entry['label']}`\n"
                f"• Destination: All matching jobs will post to **#{CHANNEL_NAME}**.\n"
                f"• URL: `{entry['url']}`"
            )
            await interaction.followup.send(msg)
            logger.info(f"Added new 99freelas tracker via slash command: {keyword}")
        except Exception as e:
            logger.error(f"Failed to add 99freelas tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to add tracker: {e}")

    @app_commands.command(
        name="99freelas_delete_tracker",
        description="Delete a search keyword from 99freelas tracking",
    )
    @app_commands.describe(keyword="The exact keyword/label to stop tracking on 99freelas")
    @app_commands.default_permissions(administrator=True)
    async def delete_tracker(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        try:
            removed = remove_tracker_by_label(keyword)
            if not removed:
                await interaction.followup.send(f"❌ Could not find a 99freelas tracker with keyword `{keyword}`.")
                return

            await interaction.followup.send(
                f"✅ 99freelas tracker `{keyword}` removed successfully. (Channel #{CHANNEL_NAME} was kept intact)."
            )
            logger.info(f"Removed 99freelas tracker via slash command: {keyword}")
        except Exception as e:
            logger.error(f"Failed to remove 99freelas tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to remove tracker: {e}")

    @app_commands.command(
        name="99freelas_list_trackers",
        description="List all currently tracked keywords for 99freelas",
    )
    async def list_trackers(self, interaction: discord.Interaction):
        if not TRACKED_QUERIES:
            await interaction.response.send_message("ℹ️ No 99freelas search queries are currently tracked.", ephemeral=True)
            return

        lines = [f"**Currently Tracked 99freelas Keywords (Posting to #{CHANNEL_NAME}):**"]
        for entry in TRACKED_QUERIES:
            lines.append(f"• `{entry.get('label')}` → <{entry.get('url')}>")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)
