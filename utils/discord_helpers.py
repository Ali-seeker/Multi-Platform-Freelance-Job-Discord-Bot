"""
utils/discord_helpers.py — Shared Discord utilities across all freelancing platforms.
"""

import asyncio
from datetime import datetime, timezone
import discord
from logger import get_logger

logger = get_logger(__name__)


async def send_with_retry(coro_func, *args, max_retries: int = 3, **kwargs):
    """
    Execute a Discord API coroutine with automatic retry on rate limiting (HTTP 429).
    """
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, "retry_after", 5.0)
                logger.warning(
                    f"Discord 429 rate limit -- waiting {retry_after:.1f}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"Discord HTTP error {e.status}: {e.text}")
                return None
    logger.error("Max retries reached for Discord API call.")
    return None


def split_message(text: str, limit: int = 1900) -> list[str]:
    """
    Split a long message into chunks that fit Discord's 2000-char limit.
    Splits at newline boundaries to avoid cutting mid-sentence.
    """
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        parts.append(current)
    return parts


def format_relative_time(iso_timestamp: str) -> str:
    """
    Convert an ISO 8601 timestamp to a human-readable relative time string.
    Examples: "2 minutes ago", "1 hour ago", "3 days ago"
    """
    if not iso_timestamp:
        return "Unknown"

    try:
        clean = iso_timestamp.replace("Z", "+00:00")
        posted = datetime.fromisoformat(clean)
        now = datetime.now(timezone.utc)
        diff = now - posted

        seconds = int(diff.total_seconds())
        if seconds < 0:
            return "Just now"
        if seconds < 60:
            return f"{seconds} seconds ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''} ago"
    except (ValueError, TypeError):
        return "Unknown"


async def get_or_create_platform_channel(
    bot: discord.Client,
    platform_name: str,
    preferred_channel_id: str | int | None = None,
    save_id_callback=None,
) -> discord.TextChannel | None:
    """
    Resolves or creates a single dedicated Discord channel for a platform (e.g. 'upwork', 'guru').

    1. Tries to retrieve channel via preferred_channel_id if given.
    2. If not found or invalid, searches all bot guilds for a channel named platform_name (case-insensitive).
    3. If none exists, creates a new text channel named platform_name in the first available guild.
    4. Invokes save_id_callback(channel_id) if a channel was found/created so config can persist it.
    """
    target_name = platform_name.lower().replace(" ", "-")

    # 1. Try preferred_channel_id if specified
    if preferred_channel_id:
        try:
            cid = int(preferred_channel_id)
            channel = bot.get_channel(cid)
            if not channel:
                channel = await bot.fetch_channel(cid)
            if channel and isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                logger.info(f"📌 Using configured channel #{channel.name} ({channel.id}) for {platform_name}")
                return channel
        except Exception as e:
            logger.warning(f"Configured channel ID {preferred_channel_id} invalid or inaccessible: {e}")

    # Wait until bot guilds are populated
    await bot.wait_until_ready()

    if not bot.guilds:
        logger.error(f"Cannot resolve or create #{target_name} channel: Bot is not connected to any guild!")
        return None

    # 2. Search guilds for existing channel named target_name
    for guild in bot.guilds:
        for ch in guild.text_channels:
            if ch.name.lower() == target_name:
                logger.info(f"🎯 Found existing channel #{ch.name} ({ch.id}) in guild '{guild.name}' for {platform_name}")
                if save_id_callback:
                    try:
                        save_id_callback(str(ch.id))
                    except Exception as err:
                        logger.error(f"Error saving resolved channel_id: {err}")
                return ch

    # 3. Create channel in the first guild where bot has permission
    for guild in bot.guilds:
        try:
            new_ch = await guild.create_text_channel(
                name=target_name,
                topic=f"Real-time {platform_name.title()} freelance job alerts and discussions.",
            )
            logger.info(f"✨ Created new channel #{new_ch.name} ({new_ch.id}) in guild '{guild.name}' for {platform_name}")
            if save_id_callback:
                try:
                    save_id_callback(str(new_ch.id))
                except Exception as err:
                    logger.error(f"Error saving created channel_id: {err}")
            return new_ch
        except discord.Forbidden:
            logger.warning(f"No permission to create channel #{target_name} in guild '{guild.name}'")
        except Exception as e:
            logger.error(f"Failed to create channel #{target_name} in guild '{guild.name}': {e}")

    logger.error(f"Failed to resolve or create channel #{target_name} across all available guilds.")
    return None
