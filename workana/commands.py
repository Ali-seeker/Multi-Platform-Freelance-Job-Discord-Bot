"""
workana/commands.py — Discord Slash Commands for managing Workana trackers.
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


class WorkanaCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="workana_add_tracker",
        description="Add a new search keyword for Workana (projects will post to #workana)",
    )
    @app_commands.describe(
        keyword="The search term for Workana projects (e.g. 'Python', 'React', 'Mobile')",
        label="Optional friendly display label (defaults to keyword)",
    )
    @app_commands.default_permissions(administrator=True)
    async def add_tracker(self, interaction: discord.Interaction, keyword: str, label: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            tracker_label = label or keyword
            add_new_tracker(keyword, tracker_label)
            msg = (
                f"✅ **Workana Tracker Added!**\n"
                f"• Keyword: `{keyword}`\n"
                f"• Label: `{tracker_label}`\n"
                f"• Destination: All matching projects will post to **#{CHANNEL_NAME}**."
            )
            await interaction.followup.send(msg)
            logger.info(f"Added new Workana tracker via slash command: {keyword} ({tracker_label})")
        except Exception as e:
            logger.error(f"Failed to add Workana tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to add tracker: {e}")

    @app_commands.command(
        name="workana_delete_tracker",
        description="Delete a search keyword from Workana tracking",
    )
    @app_commands.describe(label="The exact label/keyword of the Workana tracker to remove")
    @app_commands.default_permissions(administrator=True)
    async def delete_tracker(self, interaction: discord.Interaction, label: str):
        await interaction.response.defer(ephemeral=True)
        try:
            removed = remove_tracker_by_label(label)
            if not removed:
                await interaction.followup.send(f"❌ Could not find a Workana tracker with label `{label}`.")
                return

            await interaction.followup.send(
                f"✅ Workana tracker `{label}` removed successfully. (Channel #{CHANNEL_NAME} was kept intact)."
            )
            logger.info(f"Removed Workana tracker via slash command: {label}")
        except Exception as e:
            logger.error(f"Failed to delete Workana tracker: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to delete tracker: {e}")

    @app_commands.command(
        name="workana_list_trackers",
        description="List all active Workana search query trackers",
    )
    @app_commands.default_permissions(administrator=True)
    async def list_trackers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not TRACKED_QUERIES:
            await interaction.followup.send("ℹ️ No Workana trackers are currently configured.")
            return

        lines = [f"📋 **Active Workana Trackers ({len(TRACKED_QUERIES)})** — Channel: `#{CHANNEL_NAME}`:\n"]
        for idx, q in enumerate(TRACKED_QUERIES, 1):
            lines.append(f"**{idx}. {q.get('label', 'Unnamed')}**")
            lines.append(f"   • Query: `{q.get('query', '')}`")
            lines.append(f"   • URL: <{q.get('url', '')}>\n")

        msg = "\n".join(lines)
        await interaction.followup.send(msg)
