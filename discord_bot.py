"""
discord_bot.py — Discord bot that posts new Upwork jobs to a channel.

This is the Phase 2 entry point. It runs a Discord bot that:
  1. Polls Upwork's GraphQL API every N seconds (configurable)
  2. Checks each job against the SQLite database for duplicates
  3. Posts NEW jobs to a Discord channel with formatted messages
  4. Creates a thread on each post with full job details
  5. Handles Discord rate limiting (429) with automatic retry

Usage:
  python discord_bot.py

Requires DISCORD_TOKEN and DISCORD_CHANNEL_ID in your .env file.
"""

import sys
import io
import os
import asyncio
import psutil
import signal
import time
from datetime import datetime, timezone

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# pyrefly: ignore [missing-import]
import discord
from discord.ext import tasks
from discord import app_commands

import urllib.parse
import hashlib
from config import (
    DISCORD_TOKEN,
    TRACKED_URLS,
    POLL_INTERVAL_SECONDS,
    REQUEST_HEADERS,
    add_new_tracker,
    remove_tracker_by_label,
    update_tracker_by_label,
)
from scraper import UpworkScraper
from auth_manager import AuthManager, SessionExpiredError
from db import init_db, save_job, job_exists, get_job_count, cleanup_old_jobs, get_job_hash
from monitor import global_state, start_dashboard
from logger import get_logger

import logging
logging.getLogger("discord").setLevel(logging.WARNING)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Message Formatting
# ---------------------------------------------------------------------------

def format_relative_time(iso_timestamp: str) -> str:
    """
    Convert an ISO 8601 timestamp to a human-readable relative time string.

    Examples:
        "2 minutes ago", "1 hour ago", "3 days ago"

    Args:
        iso_timestamp: ISO 8601 datetime string (e.g., "2026-07-17T06:14:13.856Z")

    Returns:
        Human-readable relative time, or "Unknown" if parsing fails.
    """
    if not iso_timestamp:
        return "Unknown"

    try:
        # Handle both "Z" suffix and "+00:00" timezone formats
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


def build_job_url(ciphertext: str) -> str:
    """
    Build the Upwork job URL from its ciphertext identifier.

    Args:
        ciphertext: The job's ciphertext ID (e.g., "~022072926869803851328")

    Returns:
        Full Upwork job URL string.
    """
    return f"https://www.upwork.com/jobs/{ciphertext}"


def format_job_message(job: dict, details: dict = None, is_updated: bool = False) -> tuple[str, discord.Embed]:
    """
    Build a formatted Discord message for a new Upwork job posting.

    The message includes the job title, relative posting time, budget,
    experience level, current time, proposal count, client info,
    a description preview, and an apply link.

    Args:
        job: Parsed job dictionary from parse_job() (Phase 1)
        details: Optional full details dictionary from fetch_job_details()

    Returns:
        A tuple of (content_text, embed) to send to Discord.
    """
    title = job.get("title", "Untitled Job")
    ciphertext = job.get("ciphertext", "")
    job_url = build_job_url(ciphertext) if ciphertext else ""
    posted_time = job.get("posted_time", "")
    budget = job.get("budget", "Not specified")
    skills = job.get("skills", "")
    description = job.get("description", "")
    experience_level = job.get("experience_level", "Not specified")

    # Relative time (e.g., "15 minutes ago")
    relative = format_relative_time(posted_time)

    # Current time in HH:MM 24-hour format
    current_time = datetime.now().strftime("%H:%M")

    # Description preview (first 300 chars, clean up)
    desc_preview = description[:300].strip()
    if len(description) > 300:
        desc_preview += "..."

    # Determine color based on experience level
    level_lower = experience_level.lower()
    if "entry" in level_lower:
        color = 0x2ECC71  # Green
    elif "intermediate" in level_lower:
        color = 0x3498DB  # Blue
    elif "expert" in level_lower:
        color = 0xF39C12  # Gold/Orange
    else:
        color = 0x2ECC71  # Default brand green

    # Initialize Embed
    embed = discord.Embed(
        title=title,
        url=job_url if job_url else None,
        description=desc_preview if desc_preview else None,
        color=color
    )

    # Fields
    embed.add_field(name="Posted", value=relative, inline=True)
    embed.add_field(name="Budget/Rate", value=budget, inline=True)
    embed.add_field(name="Level", value=experience_level, inline=True)
    embed.add_field(name="Time", value=current_time, inline=True)

    # Proposals and Client Info removed due to Upwork API restrictions on unauthenticated requests.

    if skills:
        embed.add_field(name="Skills", value=skills, inline=False)

    # Footer and Timestamp
    embed.set_footer(text="Upwork Job Bot")
    embed.timestamp = discord.utils.utcnow()

    content = "🔄 **[UPDATED]** This job has been updated by the client!" if is_updated else ""

    return content, embed


def format_thread_details(details: dict, job: dict) -> str:
    """
    Build a detailed message for the job thread with full information.

    Contains four sections: Full Job Description, Client Details,
    Job Details, and an Apply link. This goes into the thread created
    on the main channel post.

    Args:
        details: Full details dictionary from fetch_job_details()
        job: Parsed job dictionary from parse_job() (for URL/title)

    Returns:
        Formatted string for the thread message.
    """
    ciphertext = job.get("ciphertext", "")
    job_url = build_job_url(ciphertext) if ciphertext else ""

    # --- Full Job Description ---
    description = details.get("description") or job.get("description", "No description available.")

    # --- Client Details ---
    location = details.get("client_location", "Unknown")
    member_since = details.get("client_member_since", "")
    if member_since:
        try:
            clean = member_since.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            member_since = dt.strftime("%b %Y")
        except (ValueError, TypeError):
            member_since = "Unknown"
    else:
        member_since = "Unknown"

    total_spent = details.get("client_total_spent", 0)
    spent_str = f"${total_spent:,.2f}" if total_spent else "$0"
    total_jobs = details.get("client_total_jobs", 0)
    hire_rate = details.get("client_hire_rate", 0)
    rating = details.get("client_rating", 0)
    rating_str = f"{rating}/5" if rating else "No rating"
    payment = "Verified" if details.get("payment_verified") else "Not Verified"

    # --- Job Details ---
    job_type = details.get("job_type") or job.get("job_type", "Not specified")
    budget = details.get("budget") or job.get("budget", "Not specified")
    duration = details.get("project_duration", "Not specified")
    level = details.get("experience_level") or job.get("experience_level", "Not specified")
    category = details.get("category", "Not specified")
    applicants = details.get("total_applicants", 0)
    hired = details.get("total_hired", 0)

    lines = []

    # Section 1: Full Description
    lines.append("__**Full Job Description**__")
    lines.append("")
    # Discord has a 2000 char limit per message — truncate if needed
    if len(description) > 1500:
        lines.append(description[:1500] + "...")
    else:
        lines.append(description)
    lines.append("")

    # Section 2: Client Details
    client_lines = []
    if location and location != "Unknown":
        client_lines.append(f"- **Location:** {location}")
    if member_since and member_since != "Unknown":
        client_lines.append(f"- **Member Since:** {member_since}")
    if total_spent > 0:
        client_lines.append(f"- **Total Spent:** {spent_str}")
    if total_jobs > 0:
        client_lines.append(f"- **Jobs Posted:** {total_jobs}")
        client_lines.append(f"- **Hire Rate:** {hire_rate}%")
    if rating:
        client_lines.append(f"- **Rating:** {rating_str}")
    if details and "payment_verified" in details:
        client_lines.append(f"- **Payment:** {payment}")

    if client_lines:
        lines.append("__**Client Details**__")
        lines.extend(client_lines)
        lines.append("")

    # Section 3: Job Details
    job_lines = []
    if job_type and job_type != "Not specified":
        job_lines.append(f"- **Type:** {job_type}")
    if budget and budget not in ("Not specified", "Budget not specified"):
        job_lines.append(f"- **Budget:** {budget}")
    if duration and duration != "Not specified":
        job_lines.append(f"- **Duration:** {duration}")
    if level and level != "Not specified":
        job_lines.append(f"- **Experience Level:** {level}")
    if category and category != "Not specified":
        job_lines.append(f"- **Category:** {category}")
    if details and "total_applicants" in details:
        job_lines.append(f"- **Proposals:** {applicants}")
    if details and "total_hired" in details:
        job_lines.append(f"- **Hired:** {hired}")

    if job_lines:
        lines.append("__**Job Details**__")
        lines.extend(job_lines)
        lines.append("")

    # Apply link
    if job_url:
        lines.append(f"**[Apply Here]({job_url})**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord Rate Limit Helper
# ---------------------------------------------------------------------------

async def send_with_retry(coro_func, *args, max_retries: int = 3, **kwargs):
    """
    Execute a Discord API coroutine with automatic retry on rate limiting.

    If Discord returns a 429 (rate limited), waits for the retry_after
    period and tries again. Gives up after max_retries attempts.

    Args:
        coro_func: The async function to call (e.g., channel.send)
        *args: Positional arguments for the function
        max_retries: Maximum number of retry attempts
        **kwargs: Keyword arguments for the function

    Returns:
        The result of the coroutine, or None if all retries failed.
    """
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after if hasattr(e, "retry_after") else 5.0
                logger.warning(f"Discord 429 rate limit -- waiting {retry_after:.1f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"Discord HTTP error {e.status}: {e.text}")
                return None
    logger.error("Max retries reached for Discord API call.")
    return None


# ---------------------------------------------------------------------------
# Bot Setup
# ---------------------------------------------------------------------------

# Set up intents — we need message_content for reading messages
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Create the scraper instance (reused across polling cycles)
scraper = UpworkScraper()

# Create the auth manager for automatic session refresh (Phase 3)
# Uses the same User-Agent as the scraper for Cloudflare consistency
auth_manager = AuthManager(user_agent=REQUEST_HEADERS["user-agent"])


@tree.command(name="sync", description="Sync bot commands (Admin only)")
@app_commands.default_permissions(administrator=True)
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await tree.sync()
        await interaction.followup.send("✅ Commands synced successfully!")
        logger.info("Bot commands synced.")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands: {e}")
        logger.error(f"Failed to sync commands: {e}")

@tree.command(name="add_tracker", description="Add a new Upwork job tracker and create a channel")
@app_commands.describe(keyword="The search term for the jobs (e.g., React Developer)")
@app_commands.default_permissions(administrator=True)
async def add_tracker(interaction: discord.Interaction, keyword: str):
    await interaction.response.defer(ephemeral=True)
    
    try:
        channel_name = keyword.lower().replace(" ", "-")
        category = interaction.channel.category if hasattr(interaction.channel, "category") else None
        
        new_channel = await interaction.guild.create_text_channel(name=channel_name, category=category)
        
        encoded_keyword = urllib.parse.quote(keyword)
        upwork_url = f"https://www.upwork.com/nx/search/jobs/?q={encoded_keyword}&sort=recency"
        
        add_new_tracker(url=upwork_url, channel_id=str(new_channel.id), label=keyword)
        
        await interaction.followup.send(f"✅ Tracker added successfully!\nChannel: {new_channel.mention}\nURL: `{upwork_url}`")
        logger.info(f"Added new tracker via command: {keyword} -> {new_channel.name}")
        
    except discord.Forbidden:
        await interaction.followup.send("❌ I do not have permission to create channels.")
    except Exception as e:
        logger.error(f"Failed to add tracker via command: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Failed to add tracker: {e}")
@tree.command(name="delete_tracker", description="Delete an Upwork job tracker and its channel")
@app_commands.describe(keyword="The exact keyword/label of the tracker to delete")
@app_commands.default_permissions(administrator=True)
async def delete_tracker(interaction: discord.Interaction, keyword: str):
    await interaction.response.defer(ephemeral=True)
    try:
        removed_entry = remove_tracker_by_label(keyword)
        if not removed_entry:
            await interaction.followup.send(f"❌ Could not find tracker with keyword `{keyword}`.")
            return

        channel_id_str = removed_entry.get("channel_id")
        deleted_channel = False
        
        if channel_id_str:
            channel = interaction.guild.get_channel(int(channel_id_str))
            if channel:
                await channel.delete(reason=f"Tracker '{keyword}' deleted by {interaction.user.name}")
                deleted_channel = True
                
        msg = f"✅ Tracker `{keyword}` deleted successfully!"
        if deleted_channel:
            msg += "\nChannel has also been deleted."
        else:
            msg += "\n(Associated channel was not found or already deleted)."
            
        await interaction.followup.send(msg)
        logger.info(f"Deleted tracker via command: {keyword}")
        
    except discord.Forbidden:
        await interaction.followup.send("❌ Tracker removed from config, but I do not have permission to delete the channel.")
    except Exception as e:
        logger.error(f"Failed to delete tracker via command: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Failed to completely delete tracker: {e}")

@tree.command(name="update_tracker", description="Update an existing Upwork job tracker")
@app_commands.describe(old_keyword="The current keyword of the tracker", new_keyword="The new keyword to search for")
@app_commands.default_permissions(administrator=True)
async def update_tracker(interaction: discord.Interaction, old_keyword: str, new_keyword: str):
    await interaction.response.defer(ephemeral=True)
    try:
        encoded_keyword = urllib.parse.quote(new_keyword)
        new_url = f"https://www.upwork.com/nx/search/jobs/?q={encoded_keyword}&sort=recency"
        
        updated_entry = update_tracker_by_label(old_keyword, new_keyword, new_url)
        if not updated_entry:
            await interaction.followup.send(f"❌ Could not find tracker with keyword `{old_keyword}`.")
            return

        channel_id_str = updated_entry.get("channel_id")
        updated_channel = False
        
        if channel_id_str:
            channel = interaction.guild.get_channel(int(channel_id_str))
            if channel:
                new_channel_name = new_keyword.lower().replace(" ", "-")
                await channel.edit(name=new_channel_name, reason=f"Tracker updated by {interaction.user.name}")
                updated_channel = True
                
        msg = f"✅ Tracker updated successfully from `{old_keyword}` to `{new_keyword}`!\nNew URL: `{new_url}`"
        if updated_channel:
            msg += f"\nChannel name updated to `#{(new_keyword.lower().replace(' ', '-'))}`."
            
        await interaction.followup.send(msg)
        logger.info(f"Updated tracker via command: {old_keyword} -> {new_keyword}")
        
    except discord.Forbidden:
        await interaction.followup.send("❌ Tracker updated in config, but I do not have permission to edit the channel name.")
    except Exception as e:
        logger.error(f"Failed to update tracker via command: {e}", exc_info=True)
        await interaction.followup.send(f"❌ Failed to completely update tracker: {e}")


@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    # Initialize the database
    init_db()
    
    # Commands sync karne ka code comment kar diya hai.
    # Ab commands already Discord pe save hain, to baar baar sync nahi karna paray ga.
    # try:
    #     synced = await tree.sync()
    #     logger.info(f"Synced {len(synced)} command(s).")
    # except Exception as e:
    #     logger.error(f"Failed to sync commands: {e}")

    # Start dashboard
    start_dashboard()

    # Update state
    global_state["active_urls"] = len(TRACKED_URLS)
    
    logger.info(f"🟢 Bot Online | 🤖 {bot.user} | 🔗 {len(TRACKED_URLS)} URLs | 🗄️ {get_job_count()} Jobs | 📊 Dash :5000 | ⏱️ Poll {POLL_INTERVAL_SECONDS}s")

    # Start the polling loops
    if not poll_upwork.is_running():
        poll_upwork.start()
    if not memory_monitor.is_running():
        memory_monitor.start()
    if not db_cleanup_task.is_running():
        db_cleanup_task.start()

@tasks.loop(minutes=30)
async def memory_monitor():
    mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    global_state["memory_usage_mb"] = mem_mb
    if mem_mb > 400:
        logger.warning(f"⚠️ High memory usage: {mem_mb:.2f} MB")

@tasks.loop(hours=24)
async def db_cleanup_task():
    logger.info("🧹 Running daily DB cleanup...")
    cleanup_old_jobs(14)


@tasks.loop(seconds=POLL_INTERVAL_SECONDS)
async def poll_upwork():
    """
    Background task that polls Upwork for new jobs every N seconds.
    Iterates over all tracked URLs in config.json sequentially.
    """
    if not TRACKED_URLS:
        logger.error("No tracked_urls found in config.json")
        return

    total_new_count = 0
    
    # --- Proactive refresh (secondary safety net) ---
    if auth_manager.should_refresh():
        logger.info("🔄 Proactive session refresh (scheduled)")
        result = await asyncio.to_thread(auth_manager.refresh_session, reason="proactive scheduled refresh")
        if result:
            auth_header, cookie_string = result
            scraper.update_session(auth_header, cookie_string)
            global_state["last_token_refresh"] = datetime.now().isoformat()

    for url_config in TRACKED_URLS:
        url_source = url_config["url"]
        channel_id = url_config["channel_id"]
        label = url_config["label"]

        channel = bot.get_channel(int(channel_id))
        if not channel:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except Exception as e:
                logger.error(f"Could not find channel {channel_id} for {label}: {e}")
                global_state["errors_last_hour"] += 1
                continue

        logger.info(f"🔍 Scanning: {label}")

        # Extract search query from the URL (q parameter)
        parsed_url = urllib.parse.urlparse(url_source)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        search_query = query_params.get('q', [''])[0]

        if not search_query:
            logger.warning(f"No 'q' parameter found in {url_source}. Using label as fallback.")
            search_query = label

        # --- Fetch jobs with reactive refresh on 401/403 ---
        try:
            jobs = await asyncio.to_thread(scraper.fetch_jobs, search_query)
        except SessionExpiredError:
            logger.info(f"🔄 Reactive session refresh (401/403 for {label})")
            result = await asyncio.to_thread(auth_manager.refresh_session, reason="reactive refresh triggered by 401/403")
            if result:
                auth_header, cookie_string = result
                scraper.update_session(auth_header, cookie_string)
                global_state["last_token_refresh"] = datetime.now().isoformat()
                try:
                    jobs = await asyncio.to_thread(scraper.fetch_jobs, search_query)  # Retry once with fresh session
                except SessionExpiredError:
                    logger.warning(f"⚠️ Retry failed (401/403) -- skipping {label}")
                    global_state["errors_last_hour"] += 1
                    continue
            else:
                logger.error(f"❌ Refresh failed -- skipping {label}")
                global_state["errors_last_hour"] += 1
                continue

        if not jobs:
            continue

        new_count = 0
        for job in jobs:
            if bot.is_closed():
                break

            job_id = job.get("job_id", "")
            title = job.get("title", "Untitled")

            try:
                description = job.get("description", "")
                budget = job.get("budget", "")
                
                # Compute current hash
                hash_input = f"{title}|{description}|{budget}".encode('utf-8')
                current_hash = hashlib.sha256(hash_input).hexdigest()

                stored_hash = get_job_hash(job_id, url_source)
                
                if stored_hash == current_hash:
                    # Skip if we've already seen this job and it hasn't changed
                    continue

                is_updated = (stored_hash is not None)

                # Save to database FIRST
                save_job(job, url_source, current_hash)

                new_count += 1
                total_new_count += 1
                global_state["jobs_posted_last_hour"] += 1
                
                if is_updated:
                    logger.info(f"🔄 [UPDATED] {title[:60]}")
                else:
                    logger.info(f"✨ [NEW] {title[:60]}")

                # Fetch full details for this job
                ciphertext = job.get("ciphertext", "")
                details = {}
                if ciphertext:
                    try:
                        details = await asyncio.to_thread(scraper.fetch_job_details, ciphertext)
                    except SessionExpiredError:
                        logger.info("🔄 Reactive session refresh (401/403 on details)")
                        result = await asyncio.to_thread(auth_manager.refresh_session, reason="reactive refresh triggered by 401/403")
                        if result:
                            auth_header, cookie_string = result
                            scraper.update_session(auth_header, cookie_string)
                            global_state["last_token_refresh"] = datetime.now().isoformat()
                            try:
                                details = await asyncio.to_thread(scraper.fetch_job_details, ciphertext)  # Retry once
                            except SessionExpiredError:
                                logger.warning("⚠️ Retry failed for job details")

                # Format and send the main message
                content_text, embed = format_job_message(job, details, is_updated=is_updated)
                thread_name = f"Job: {title[:80]}"
                thread = None

                if isinstance(channel, discord.ForumChannel):
                    # Forum channel requires creating a thread directly with the content
                    try:
                        thread_with_msg = await send_with_retry(
                            channel.create_thread,
                            name=thread_name,
                            content=content_text,
                            embed=embed,
                            auto_archive_duration=60,
                        )
                        if thread_with_msg:
                            thread = thread_with_msg.thread
                    except Exception as e:
                        logger.error(f"Failed to create forum thread: {e}")
                        global_state["errors_last_hour"] += 1
                        continue
                else:
                    # Standard TextChannel
                    sent_message = await send_with_retry(channel.send, content=content_text, embed=embed)
                    if sent_message is None:
                        logger.error(f"Failed to post job: {title[:40]}")
                        global_state["errors_last_hour"] += 1
                        continue

                    try:
                        thread = await send_with_retry(
                            sent_message.create_thread,
                            name=thread_name,
                            auto_archive_duration=60,
                        )
                    except Exception as e:
                        logger.error(f"Failed to create thread: {e}")
                        global_state["errors_last_hour"] += 1

                # Post the thread details
                if thread:
                    thread_text = format_thread_details(details, job)
                    # Split into multiple messages if over Discord's 2000 char limit
                    if len(thread_text) > 2000:
                        parts = _split_message(thread_text)
                        for part in parts:
                            await send_with_retry(thread.send, part)
                    else:
                        await send_with_retry(thread.send, thread_text)
            except Exception as e:
                logger.error(f"Exception raised while processing job {job_id} ({title}): {e}", exc_info=True)
                global_state["errors_last_hour"] += 1
                continue
        
        if new_count > 0:
            logger.info(f"✅ {label}: Found {new_count} new jobs.")
        
        # Pause briefly before checking the next URL to avoid slamming the API
        await asyncio.sleep(2)

    if total_new_count > 0:
        logger.info(f"📫 Cycle Complete: {total_new_count} posted | Total DB: {get_job_count()}")

    # Refresh memory stats
    global_state["memory_usage_mb"] = psutil.Process().memory_info().rss / (1024 * 1024)


def _split_message(text: str, limit: int = 1900) -> list[str]:
    """
    Split a long message into chunks that fit Discord's 2000-char limit.

    Splits at newline boundaries to avoid cutting mid-sentence.

    Args:
        text: The full message text to split
        limit: Maximum characters per chunk (default 1900 for safety margin)

    Returns:
        List of message chunks.
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


@poll_upwork.before_loop
async def before_poll():
    """Wait until the bot is fully ready before starting the poll loop."""
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

_shutdown_count = 0

def shutdown_handler(signum, frame):
    """Handle graceful shutdown for signals, with force-quit on double press."""
    global _shutdown_count
    _shutdown_count += 1
    
    if _shutdown_count >= 2:
        logger.warning("Second shutdown signal received. Forcing immediate exit...")
        os._exit(1)
        
    logger.info("Received shutdown signal. Closing gracefully... (Press Ctrl+C again to force quit)")
    try:
        if poll_upwork.is_running():
            poll_upwork.cancel()
        if memory_monitor.is_running():
            memory_monitor.cancel()
        if db_cleanup_task.is_running():
            db_cleanup_task.cancel()

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(bot.close())
        else:
            sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set in your .env file.")
        logger.error("   -> Get your bot token from https://discord.com/developers/applications")
        sys.exit(1)

    logger.info("🚀 Starting Upwork Discord Bot...")

    # Register graceful shutdown signals if supported on OS
    try:
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
    except NotImplementedError:
        pass

    bot.run(DISCORD_TOKEN, log_handler=None)
