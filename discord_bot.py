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
import asyncio
from datetime import datetime, timezone

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import discord
from discord.ext import tasks

from config import (
    DISCORD_TOKEN,
    DISCORD_CHANNEL_ID,
    SEARCH_QUERY,
    POLL_INTERVAL_SECONDS,
)
from scraper import UpworkScraper
from db import init_db, save_job, job_exists, get_job_count


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


def format_job_message(job: dict, details: dict = None) -> str:
    """
    Build a formatted Discord message for a new Upwork job posting.

    The message includes the job title, relative posting time, budget,
    experience level, current time, proposal count, client info,
    a description preview, and an apply link.

    Args:
        job: Parsed job dictionary from parse_job() (Phase 1)
        details: Optional full details dictionary from fetch_job_details()

    Returns:
        Formatted string ready to send to Discord.
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

    # Build the message sections
    lines = []
    lines.append(f"**{title}**")
    lines.append("")
    lines.append(f"**Posted:** {relative}")
    lines.append(f"**Budget/Rate:** {budget}")
    lines.append(f"**Level:** {experience_level}")
    lines.append(f"**Time:** {current_time}")

    # Add details-specific fields if available
    if details:
        applicants = details.get("total_applicants", 0)
        lines.append(f"**Proposals:** {applicants}")

        # Client info
        payment = "Verified" if details.get("payment_verified") else "Not Verified"
        location = details.get("client_location", "Unknown")
        total_spent = details.get("client_total_spent", 0)
        spent_str = f"${total_spent:,.2f}" if total_spent else "$0"
        lines.append(f"**Client Info:** Payment {payment} | {location} | {spent_str} spent")
    else:
        lines.append("**Proposals:** Loading...")
        lines.append("**Client Info:** Loading...")

    lines.append("")
    lines.append(f"**Skills:** {skills}")
    lines.append("")
    lines.append(f"> {desc_preview}")
    lines.append("")

    if job_url:
        lines.append(f"**[Apply Here]({job_url})**")

    return "\n".join(lines)


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
    description = details.get("description", "No description available.")

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
    job_type = details.get("job_type", "Not specified")
    budget = details.get("budget", "Not specified")
    duration = details.get("project_duration", "Not specified")
    level = details.get("experience_level", "Not specified")
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
    lines.append("__**Client Details**__")
    lines.append(f"- **Location:** {location}")
    lines.append(f"- **Member Since:** {member_since}")
    lines.append(f"- **Total Spent:** {spent_str}")
    lines.append(f"- **Jobs Posted:** {total_jobs}")
    lines.append(f"- **Hire Rate:** {hire_rate}%")
    lines.append(f"- **Rating:** {rating_str}")
    lines.append(f"- **Payment:** {payment}")
    lines.append("")

    # Section 3: Job Details
    lines.append("__**Job Details**__")
    lines.append(f"- **Type:** {job_type}")
    lines.append(f"- **Budget:** {budget}")
    lines.append(f"- **Duration:** {duration}")
    lines.append(f"- **Experience Level:** {level}")
    lines.append(f"- **Category:** {category}")
    lines.append(f"- **Proposals:** {applicants}")
    lines.append(f"- **Hired:** {hired}")
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
                print(f"[RATE LIMIT] Discord 429 -- waiting {retry_after:.1f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(retry_after)
            else:
                print(f"[ERROR] Discord HTTP error {e.status}: {e.text}")
                return None
    print("[ERROR] Max retries reached for Discord API call.")
    return None


# ---------------------------------------------------------------------------
# Bot Setup
# ---------------------------------------------------------------------------

# Set up intents — we need message_content for reading messages
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

# Create the scraper instance (reused across polling cycles)
scraper = UpworkScraper()


@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    print(f"[BOT] Logged in as {bot.user}")
    print(f"[BOT] Monitoring channel: {DISCORD_CHANNEL_ID}")
    print(f"[BOT] Polling every {POLL_INTERVAL_SECONDS} seconds")
    print(f"[BOT] Search query: \"{SEARCH_QUERY}\"")
    print()

    # Initialize the database
    init_db()
    print(f"[DB] Database ready -- {get_job_count()} existing jobs")

    # Start the polling loop
    if not poll_upwork.is_running():
        poll_upwork.start()


@tasks.loop(seconds=POLL_INTERVAL_SECONDS)
async def poll_upwork():
    """
    Background task that polls Upwork for new jobs every N seconds.

    For each new job found:
      1. Saves it to the SQLite database
      2. Fetches full job details (second GraphQL request)
      3. Posts a formatted message to the Discord channel
      4. Creates a thread on that message with full details
    """
    channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
    if not channel:
        print(f"[ERROR] Could not find channel {DISCORD_CHANNEL_ID}")
        print("   -> Make sure the bot has access to this channel.")
        return

    # Fetch jobs from Upwork
    jobs = scraper.fetch_jobs(SEARCH_QUERY)
    if not jobs:
        return

    new_count = 0
    for job in jobs:
        job_id = job.get("job_id", "")

        # Skip if we've already seen this job
        if job_exists(job_id):
            continue

        # Save to database FIRST (so we don't re-post if Discord fails)
        was_saved = save_job(job)
        if not was_saved:
            continue

        new_count += 1
        title = job.get("title", "Untitled")
        print(f"  [NEW] {title[:60]}")

        # Fetch full details for this job
        ciphertext = job.get("ciphertext", "")
        details = {}
        if ciphertext:
            details = scraper.fetch_job_details(ciphertext)

        # Format and send the main message
        message_text = format_job_message(job, details)
        thread_name = f"Job: {title[:80]}"
        thread = None

        if isinstance(channel, discord.ForumChannel):
            # Forum channel requires creating a thread directly with the content
            try:
                thread_with_msg = await send_with_retry(
                    channel.create_thread,
                    name=thread_name,
                    content=message_text,
                    auto_archive_duration=60,
                )
                if thread_with_msg:
                    thread = thread_with_msg.thread
            except Exception as e:
                print(f"  [ERROR] Failed to create forum thread: {e}")
                continue
        else:
            # Standard TextChannel
            sent_message = await send_with_retry(channel.send, message_text)
            if sent_message is None:
                print(f"  [ERROR] Failed to post job: {title[:40]}")
                continue

            if details:
                try:
                    thread = await send_with_retry(
                        sent_message.create_thread,
                        name=thread_name,
                        auto_archive_duration=60,
                    )
                except Exception as e:
                    print(f"  [ERROR] Failed to create thread: {e}")

        # Post the thread details
        if thread and details:
            thread_text = format_thread_details(details, job)
            # Split into multiple messages if over Discord's 2000 char limit
            if len(thread_text) > 2000:
                parts = _split_message(thread_text)
                for part in parts:
                    await send_with_retry(thread.send, part)
            else:
                await send_with_retry(thread.send, thread_text)

    if new_count > 0:
        print(f"[SUMMARY] Posted {new_count} new jobs to Discord. "
              f"Total in DB: {get_job_count()}")


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

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("[ERROR] DISCORD_TOKEN is not set in your .env file.")
        print("   -> Get your bot token from https://discord.com/developers/applications")
        sys.exit(1)
    if not DISCORD_CHANNEL_ID:
        print("[ERROR] DISCORD_CHANNEL_ID is not set in your .env file.")
        print("   -> Right-click the channel in Discord -> 'Copy Channel ID'")
        sys.exit(1)

    print("=" * 60)
    print("  Upwork Job Scraper -- Phase 2 (Discord Bot)")
    print("=" * 60)
    print()

    bot.run(DISCORD_TOKEN)
