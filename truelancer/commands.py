"""
truelancer/commands.py — Discord slash commands for Truelancer platform management.
"""

import discord
from discord import app_commands
from discord.ext import commands

from truelancer.config import (
    TRACKED_QUERIES,
    add_new_tracker,
    remove_tracker_by_label,
)
from logger import get_logger

logger = get_logger(__name__)


class TruelancerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="truelancer_add_tracker",
        description="Add a new query/keyword to track on Truelancer (posts to #truelancer)",
    )
    @app_commands.describe(
        keyword_or_url="Search term (e.g. 'automation') or Truelancer search URL",
        label="Optional friendly display name for this tracker",
    )
    async def add_tracker_cmd(
        self, interaction: discord.Interaction, keyword_or_url: str, label: str = ""
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            tracker = add_new_tracker(keyword_or_url, label)
            lbl = tracker.get("label", keyword_or_url)
            query = tracker.get("query", keyword_or_url)
            await interaction.followup.send(
                f"✅ **Truelancer Tracker Added!**\n"
                f"- **Label:** `{lbl}`\n"
                f"- **Query:** `{query}`\n"
                f"- **Channel:** `#truelancer`",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Failed to add Truelancer tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to add tracker: {e}", ephemeral=True)

    @app_commands.command(
        name="truelancer_delete_tracker",
        description="Delete a tracked Truelancer query by its label",
    )
    @app_commands.describe(label="The label of the Truelancer tracker to remove")
    async def delete_tracker_cmd(self, interaction: discord.Interaction, label: str):
        await interaction.response.defer(ephemeral=True)
        try:
            removed = remove_tracker_by_label(label)
            if removed:
                await interaction.followup.send(
                    f"🗑️ **Truelancer Tracker Removed!**\n- **Label:** `{label}`",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"⚠️ Tracker `{label}` not found in Truelancer tracked queries.",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error(f"Failed to delete Truelancer tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to delete tracker: {e}", ephemeral=True)

    @app_commands.command(
        name="truelancer_list_trackers",
        description="List all active search queries tracked on Truelancer",
    )
    async def list_trackers_cmd(self, interaction: discord.Interaction):
        if not TRACKED_QUERIES:
            await interaction.response.send_message(
                "ℹ️ No active Truelancer trackers configured.", ephemeral=True
            )
            return

        lines = ["📋 **Active Truelancer Trackers:**"]
        for idx, t in enumerate(TRACKED_QUERIES, start=1):
            lbl = t.get("label", "Unknown")
            q = t.get("query", "N/A")
            lines.append(f"{idx}. **{lbl}** — query: `{q}` (posts to `#truelancer`)")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TruelancerCommands(bot))
