"""
peopleperhour/commands.py — Discord Slash Commands for managing PeoplePerHour trackers.
"""

import discord
from discord.ext import commands
from discord import app_commands
from peopleperhour.config import (
    TRACKED_QUERIES,
    add_new_tracker,
    remove_tracker_by_label,
    CHANNEL_NAME,
)
from logger import get_logger

logger = get_logger(__name__)


class PeoplePerHourCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="pph_add_tracker",
        description="Add a new search keyword for PeoplePerHour (jobs will post to #peopleperhour)",
    )
    @app_commands.describe(keyword="The search term for PeoplePerHour jobs (e.g. 'Automation', 'Python')")
    @app_commands.default_permissions(administrator=True)
    async def add_tracker(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = add_new_tracker(keyword)
            msg = (
                f"✅ **PeoplePerHour Tracker Added!**\n"
                f"• Keyword: `{entry['label']}`\n"
                f"• Destination: All matching jobs will post to **#{CHANNEL_NAME}**.\n"
                f"• URL: `{entry['url']}`"
            )
            await interaction.followup.send(msg)
            logger.info(f"Added new PeoplePerHour tracker via slash command: {keyword}")
        except Exception as e:
            logger.error(f"Failed to add PeoplePerHour tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to add tracker: {e}")

    @app_commands.command(
        name="pph_delete_tracker",
        description="Delete a search keyword from PeoplePerHour tracking",
    )
    @app_commands.describe(keyword="The exact keyword/label to stop tracking on PeoplePerHour")
    @app_commands.default_permissions(administrator=True)
    async def delete_tracker(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        try:
            removed = remove_tracker_by_label(keyword)
            if not removed:
                await interaction.followup.send(f"❌ Could not find a PeoplePerHour tracker with keyword `{keyword}`.")
                return

            await interaction.followup.send(
                f"✅ PeoplePerHour tracker `{keyword}` removed successfully. (Channel #{CHANNEL_NAME} was kept intact)."
            )
            logger.info(f"Removed PeoplePerHour tracker: {keyword}")
        except Exception as e:
            logger.error(f"Failed to delete PeoplePerHour tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to delete tracker: {e}")

    @app_commands.command(
        name="pph_list_trackers",
        description="List all currently tracked search queries for PeoplePerHour",
    )
    async def list_trackers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not TRACKED_QUERIES:
            await interaction.followup.send("ℹ️ No keywords are currently tracked for PeoplePerHour.")
            return

        lines = [f"📋 **Tracked Queries for PeoplePerHour (posting to #{CHANNEL_NAME}):**"]
        for i, q in enumerate(TRACKED_QUERIES, 1):
            label = q.get("label", q.get("query", "Unknown"))
            lines.append(f"{i}. `{label}`")
        await interaction.followup.send("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(PeoplePerHourCommands(bot))
