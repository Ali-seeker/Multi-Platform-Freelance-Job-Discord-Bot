"""
facebook/commands.py — Discord slash commands for Facebook group post tracking.
"""

import discord
from discord import app_commands
from discord.ext import commands

from facebook.config import (
    TRACKED_QUERIES,
    TRACKED_GROUPS,
    CHANNEL_NAME,
    FB_EMAIL_USER,
    FB_EMAIL_HOST,
    FB_EMAIL_FOLDER,
    POLL_INTERVAL_SECONDS,
    add_new_tracker,
    remove_tracker_by_label,
)
from db import get_job_count
from logger import get_logger

logger = get_logger(__name__)


class FacebookCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="facebook_status",
        description="Check status and configuration of the Facebook email notification monitor.",
    )
    async def facebook_status(self, interaction: discord.Interaction):
        total_jobs = get_job_count("facebook")
        configured = bool(FB_EMAIL_USER)
        masked_user = (
            f"{FB_EMAIL_USER[:3]}***@{FB_EMAIL_USER.split('@')[-1]}"
            if "@" in FB_EMAIL_USER
            else ("Configured" if configured else "Not configured")
        )

        embed = discord.Embed(
            title="📱 Facebook Group Notification Status",
            color=0x1877F2,
        )
        embed.add_field(name="Target Channel", value=f"#{CHANNEL_NAME}", inline=True)
        embed.add_field(name="Total Posts in DB", value=str(total_jobs), inline=True)
        embed.add_field(name="Poll Interval", value=f"{POLL_INTERVAL_SECONDS}s", inline=True)
        embed.add_field(name="Email Account", value=masked_user, inline=True)
        embed.add_field(name="IMAP Host", value=FB_EMAIL_HOST, inline=True)
        embed.add_field(name="IMAP Folder", value=FB_EMAIL_FOLDER, inline=True)
        embed.add_field(
            name="Connection Status",
            value="🟢 Ready" if configured else "🔴 Missing credentials in .env",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="facebook_list_trackers",
        description="List all active keywords and filters for Facebook group monitoring.",
    )
    async def list_trackers(self, interaction: discord.Interaction):
        if not TRACKED_QUERIES:
            await interaction.response.send_message(
                "ℹ️ No active keyword filters. Currently capturing **all** group notifications.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📱 Facebook Active Trackers",
            description=f"Posts are monitored via email notifications and sent to #{CHANNEL_NAME}:",
            color=0x1877F2,
        )

        for item in TRACKED_QUERIES:
            embed.add_field(
                name=f"🔍 {item.get('label', 'Query')}",
                value=f"Filter keyword: `{item.get('query', 'all')}`",
                inline=False,
            )

        if TRACKED_GROUPS:
            embed.add_field(
                name="👥 Restricted Groups",
                value=", ".join(f"`{g}`" for g in TRACKED_GROUPS),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="facebook_add_tracker",
        description="Add a keyword filter for Facebook group posts (use 'all' to monitor every post).",
    )
    @app_commands.describe(
        keyword="Keyword to match in the post content (or 'all' for every post)",
        label="Display label for this filter",
    )
    async def add_tracker(
        self, interaction: discord.Interaction, keyword: str, label: str = ""
    ):
        entry = add_new_tracker(keyword, label)
        await interaction.response.send_message(
            f"✅ Added Facebook keyword tracker: **{entry.get('label')}** (`{entry.get('query')}`). "
            f"Matching group posts will post to #{CHANNEL_NAME}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="facebook_delete_tracker",
        description="Remove a keyword filter from Facebook group monitoring.",
    )
    @app_commands.describe(label="Label of the tracker to remove")
    async def delete_tracker(self, interaction: discord.Interaction, label: str):
        removed = remove_tracker_by_label(label)
        if removed:
            await interaction.response.send_message(
                f"🗑️ Removed Facebook tracker: **{removed.get('label')}**",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ No Facebook tracker found with label '{label}'. Use `/facebook_list_trackers` to view active trackers.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(FacebookCommands(bot))
