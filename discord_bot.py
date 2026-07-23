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
import signal

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
)
sys.stderr = io.TextIOWrapper(
    sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
)

import discord
from discord.ext import commands

from config import DISCORD_TOKEN, TRACKED_URLS, REQUEST_HEADERS, POLL_INTERVAL_SECONDS
from scraper import UpworkScraper
from auth_manager import AuthManager
from db import init_db, get_job_count
from monitor import global_state, start_dashboard
from logger import get_logger

import logging

logging.getLogger("discord").setLevel(logging.WARNING)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Bot Setup
# ---------------------------------------------------------------------------

# Set up intents — we need message_content for reading messages
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Create the scraper instance (reused across polling cycles)
scraper = UpworkScraper()

# Create the auth manager for automatic session refresh (Phase 3)
# Uses the same User-Agent as the scraper for Cloudflare consistency
auth_manager = AuthManager(user_agent=REQUEST_HEADERS["user-agent"])


@bot.event
async def setup_hook():
    """Called automatically when the bot is initializing."""
    # Initialize the database BEFORE loading cogs or starting loops
    init_db()

    # Load Cogs (Modules)
    await bot.load_extension("cogs.tracker_commands")

    # The poller needs dependencies, so we load it slightly differently
    from cogs.poller import setup as setup_poller

    await setup_poller(bot, scraper, auth_manager)


@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    # Start dashboard
    start_dashboard()

    # Update state
    global_state["active_urls"] = len(TRACKED_URLS)

    logger.info(
        f"🟢 Bot Online | 🤖 {bot.user} | 🔗 {len(TRACKED_URLS)} URLs | 🗄️ {get_job_count()} Jobs | 📊 Dash :5000 | ⏱️ Poll {POLL_INTERVAL_SECONDS}s"
    )


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

    logger.info(
        "Received shutdown signal. Closing gracefully... (Press Ctrl+C again to force quit)"
    )
    try:
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
        logger.error(
            "   -> Get your bot token from https://discord.com/developers/applications"
        )
        sys.exit(1)

    logger.info("🚀 Starting Upwork Discord Bot...")

    # Register graceful shutdown signals if supported on OS
    try:
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
    except NotImplementedError:
        pass

    bot.run(DISCORD_TOKEN, log_handler=None)
