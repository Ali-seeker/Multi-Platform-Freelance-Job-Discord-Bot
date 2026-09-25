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


def parse_posted_time(raw_time: str) -> tuple[datetime | None, str, str]:
    """
    Parses a raw posted time (ISO timestamp from Upwork, or relative/date string from Guru)
    into a timezone-aware UTC datetime and Discord timestamp strings.

    Returns:
        (datetime_utc, exact_display, relative_display)
        - datetime_utc: datetime object in UTC (or None if unparseable)
        - exact_display: Discord <t:UNIX:f> (localized date + time) and UTC text
        - relative_display: Discord <t:UNIX:R> (dynamic relative time like '10 minutes ago')
    """
    if not raw_time:
        return None, "Unknown", "Unknown"

    raw = str(raw_time).strip()
    dt = None

    # 1. Try parsing numeric UNIX timestamp (Freelancer format: 1790323624)
    try:
        val = float(raw)
        if val > 100000000:  # Valid epoch
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
    except (ValueError, TypeError):
        pass

    # 2. Try parsing ISO 8601 (Upwork format: 2026-09-24T18:07:56.140Z)
    if not dt:
        try:
            clean = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass

    # 2. Try parsing relative time strings (Guru format: '13 hrs ago', '25 mins ago', 'yesterday')
    if not dt:
        import re
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        m = re.search(r"(\d+)\s*(sec|second|s|min|minute|m|hr|hour|h|day|d)s?\s*ago", raw, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            unit = m.group(2).lower()
            if unit.startswith("s"):
                dt = now - timedelta(seconds=val)
            elif unit.startswith("m"):
                dt = now - timedelta(minutes=val)
            elif unit.startswith("h"):
                dt = now - timedelta(hours=val)
            elif unit.startswith("d"):
                dt = now - timedelta(days=val)
        elif "yesterday" in raw.lower():
            dt = now - timedelta(days=1)
        elif "just now" in raw.lower() or "recent" in raw.lower():
            dt = now
        else:
            # 3. Try parsing date format: 'on Sep 24, 2026' or 'Sep 24, 2026'
            m_date = re.search(r"(?:on\s+)?([A-Za-z]{3,}\s+\d{1,2},\s*\d{4})", raw, re.IGNORECASE)
            if m_date:
                try:
                    dt = datetime.strptime(m_date.group(1), "%b %d, %Y").replace(tzinfo=timezone.utc)
                except Exception:
                    pass

    if dt:
        epoch = int(dt.timestamp())
        exact_display = f"<t:{epoch}:f>"
        relative_display = f"<t:{epoch}:R>"
        return dt, exact_display, relative_display

    return None, raw, raw


def format_relative_time(iso_timestamp: str) -> str:
    """
    Convert an ISO 8601 timestamp to a human-readable relative time string.
    Examples: "2 minutes ago", "1 hour ago", "3 days ago"
    """
    if not iso_timestamp:
        return "Unknown"

    dt, _, rel = parse_posted_time(iso_timestamp)
    if dt:
        epoch = int(dt.timestamp())
        return f"<t:{epoch}:R>"

    return iso_timestamp


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
