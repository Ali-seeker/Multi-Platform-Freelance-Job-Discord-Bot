"""
cogs/tracker_commands.py — Discord Cog for managing Upwork tracker slash commands.
"""

import urllib.parse
import discord
from discord.ext import commands
from discord import app_commands
from config import add_new_tracker, remove_tracker_by_label, update_tracker_by_label
from logger import get_logger

logger = get_logger(__name__)


class TrackerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync", description="Sync bot commands (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # We assume tree is bound to bot in discord_bot.py, but for Cogs
            # bot.tree is available
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Commands synced successfully!")
            logger.info("Bot commands synced.")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to sync commands: {e}")
            logger.error(f"Failed to sync commands: {e}")

    @app_commands.command(
        name="add_tracker",
        description="Add a new Upwork job tracker and create a channel",
    )
    @app_commands.describe(
        keyword="The search term for the jobs (e.g., React Developer)"
    )
    @app_commands.default_permissions(administrator=True)
    async def add_tracker(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)

        try:
            channel_name = keyword.lower().replace(" ", "-")
            category = (
                interaction.channel.category
                if hasattr(interaction.channel, "category")
                else None
            )

            new_channel = await interaction.guild.create_text_channel(
                name=channel_name, category=category
            )

            encoded_keyword = urllib.parse.quote(keyword)
            upwork_url = f"https://www.upwork.com/nx/search/jobs/?q={encoded_keyword}&sort=recency"

            add_new_tracker(
                url=upwork_url, channel_id=str(new_channel.id), label=keyword
            )

            await interaction.followup.send(
                f"✅ Tracker added successfully!\nChannel: {new_channel.mention}\nURL: `{upwork_url}`"
            )
            logger.info(
                f"Added new tracker via command: {keyword} -> {new_channel.name}"
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I do not have permission to create channels."
            )
        except Exception as e:
            logger.error(f"Failed to add tracker via command: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to add tracker: {e}")

    @app_commands.command(
        name="delete_tracker",
        description="Delete an Upwork job tracker and its channel",
    )
    @app_commands.describe(keyword="The exact keyword/label of the tracker to delete")
    @app_commands.default_permissions(administrator=True)
    async def delete_tracker(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer(ephemeral=True)
        try:
            removed_entry = remove_tracker_by_label(keyword)
            if not removed_entry:
                await interaction.followup.send(
                    f"❌ Could not find tracker with keyword `{keyword}`."
                )
                return

            channel_id_str = removed_entry.get("channel_id")
            deleted_channel = False

            if channel_id_str:
                channel = interaction.guild.get_channel(int(channel_id_str))
                if channel:
                    await channel.delete(
                        reason=f"Tracker '{keyword}' deleted by {interaction.user.name}"
                    )
                    deleted_channel = True

            msg = f"✅ Tracker `{keyword}` deleted successfully!"
            if deleted_channel:
                msg += "\nChannel has also been deleted."
            else:
                msg += "\n(Associated channel was not found or already deleted)."

            await interaction.followup.send(msg)
            logger.info(f"Deleted tracker via command: {keyword}")

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Tracker removed from config, but I do not have permission to delete the channel."
            )
        except Exception as e:
            logger.error(f"Failed to delete tracker via command: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ Failed to completely delete tracker: {e}"
            )

    @app_commands.command(
        name="update_tracker", description="Update an existing Upwork job tracker"
    )
    @app_commands.describe(
        old_keyword="The current keyword of the tracker",
        new_keyword="The new keyword to search for",
    )
    @app_commands.default_permissions(administrator=True)
    async def update_tracker(
        self, interaction: discord.Interaction, old_keyword: str, new_keyword: str
    ):
        await interaction.response.defer(ephemeral=True)
        try:
            encoded_keyword = urllib.parse.quote(new_keyword)
            new_url = f"https://www.upwork.com/nx/search/jobs/?q={encoded_keyword}&sort=recency"

            updated_entry = update_tracker_by_label(old_keyword, new_keyword, new_url)
            if not updated_entry:
                await interaction.followup.send(
                    f"❌ Could not find tracker with keyword `{old_keyword}`."
                )
                return

            channel_id_str = updated_entry.get("channel_id")
            updated_channel = False

            if channel_id_str:
                channel = interaction.guild.get_channel(int(channel_id_str))
                if channel:
                    new_channel_name = new_keyword.lower().replace(" ", "-")
                    await channel.edit(
                        name=new_channel_name,
                        reason=f"Tracker updated by {interaction.user.name}",
                    )
                    updated_channel = True

            msg = f"✅ Tracker updated successfully from `{old_keyword}` to `{new_keyword}`!\nNew URL: `{new_url}`"
            if updated_channel:
                msg += f"\nChannel name updated to `#{(new_keyword.lower().replace(' ', '-'))}`."

            await interaction.followup.send(msg)
            logger.info(f"Updated tracker via command: {old_keyword} -> {new_keyword}")

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Tracker updated in config, but I do not have permission to edit the channel name."
            )
        except Exception as e:
            logger.error(f"Failed to update tracker via command: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ Failed to completely update tracker: {e}"
            )


async def setup(bot):
    await bot.add_cog(TrackerCommands(bot))
