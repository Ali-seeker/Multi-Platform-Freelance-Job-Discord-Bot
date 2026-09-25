"""
main.py — Multi-platform runner for Freelance Job Discord Bots.

Run a specific platform of your choice:
  python main.py --platform upwork
  python main.py --platform guru

Or run all platforms in parallel in one process:
  python main.py --platform all
  python main.py --all

Or run different platforms in separate terminals:
  Terminal 1: python main.py --platform upwork
  Terminal 2: python main.py --platform guru
"""

import sys
import io
import os
import asyncio
import signal
import argparse
import logging
from dotenv import load_dotenv

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
)
sys.stderr = io.TextIOWrapper(
    sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
)

load_dotenv()

import discord
from discord.ext import commands

from logger import get_logger
from monitor import global_state, start_dashboard
from db import init_db, get_job_count, get_all_job_counts

logging.getLogger("discord").setLevel(logging.WARNING)
logger = get_logger("runner")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ---------------------------------------------------------------------------
# Platform Registry
# ---------------------------------------------------------------------------
# When you add a new platform (e.g. 'guru', 'peopleperhour'), register its
# setup function here.
AVAILABLE_PLATFORMS = {
    "upwork": {
        "name": "Upwork",
        "setup": lambda bot: _setup_upwork_platform(bot),
    },
    "guru": {
        "name": "Guru",
        "setup": lambda bot: _setup_guru_platform(bot),
    },
    "freelancer": {
        "name": "Freelancer",
        "setup": lambda bot: _setup_freelancer_platform(bot),
    },
}


async def _setup_upwork_platform(bot: commands.Bot):
    """Sets up Upwork platform components."""
    from upwork import setup_upwork
    await setup_upwork(bot)


async def _setup_guru_platform(bot: commands.Bot):
    """Sets up Guru platform components."""
    from guru import setup_guru
    await setup_guru(bot)


async def _setup_freelancer_platform(bot: commands.Bot):
    """Sets up Freelancer.com platform components."""
    from freelancer import setup_freelancer
    await setup_freelancer(bot)


# ---------------------------------------------------------------------------
# Bot Factory & Runner
# ---------------------------------------------------------------------------

def create_bot(target_platforms: list[str]) -> commands.Bot:
    """Builds and configures the discord.py bot instance for selected platforms."""
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def setup_hook():
        # Initialize database tables for all target platforms
        for p in target_platforms:
            init_db(platform=p)
            logger.info(f"🗄️ Initialized database table for platform '{p}'")

        # Load platform components
        for p in target_platforms:
            if p in AVAILABLE_PLATFORMS:
                setup_fn = AVAILABLE_PLATFORMS[p]["setup"]
                await setup_fn(bot)
                logger.info(f"🧩 Loaded platform engine: {AVAILABLE_PLATFORMS[p]['name']}")
            else:
                logger.warning(f"Platform '{p}' is not yet registered in AVAILABLE_PLATFORMS.")

    @bot.event
    async def on_ready():
        start_dashboard()
        global_state["platform"] = ",".join(target_platforms)
        
        counts = get_all_job_counts()
        summary_counts = " | ".join(f"{p.title()}: {cnt} jobs" for p, cnt in counts.items())
        platforms_str = ", ".join(AVAILABLE_PLATFORMS[p]["name"] for p in target_platforms if p in AVAILABLE_PLATFORMS)
        logger.info(
            f"🟢 Bot Online | 🤖 {bot.user} | 🌐 Platforms: [{platforms_str}] | 🗄️ {summary_counts or '0 jobs'} | 📊 Dash :5000"
        )

    return bot


_shutdown_count = 0


def shutdown_handler(signum, frame, bot: commands.Bot):
    """Handle graceful shutdown signals with force quit on double press."""
    global _shutdown_count
    _shutdown_count += 1

    if _shutdown_count >= 2:
        logger.warning("Second shutdown signal received. Forcing immediate exit...")
        os._exit(1)

    logger.info("Received shutdown signal. Closing gracefully... (Press Ctrl+C again to force quit)")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(bot.close())
        else:
            sys.exit(0)
    except Exception:
        sys.exit(0)


def run_platform(target_platforms: list[str]):
    """Runs the Discord bot for the requested platforms."""
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set in your .env file.")
        logger.error("   -> Get your bot token from https://discord.com/developers/applications")
        sys.exit(1)

    platforms_display = ", ".join(p.upper() for p in target_platforms)
    logger.info(f"🚀 Starting Freelance Job Bot for [{platforms_display}]...")

    bot = create_bot(target_platforms)

    try:
        signal.signal(signal.SIGINT, lambda s, f: shutdown_handler(s, f, bot))
        signal.signal(signal.SIGTERM, lambda s, f: shutdown_handler(s, f, bot))
    except (NotImplementedError, ValueError):
        pass

    bot.run(DISCORD_TOKEN, log_handler=None)


def main():
    parser = argparse.ArgumentParser(
        description="Freelance Job Alerts Discord Bot (Multi-Platform)"
    )
    parser.add_argument(
        "--platform",
        "-p",
        type=str,
        default="upwork",
        help="Platform to run: 'upwork', 'guru', 'freelancer', or 'all'. Default: 'upwork'",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Run all available platforms in parallel in this process",
    )

    args = parser.parse_args()

    if args.all or args.platform.lower() == "all":
        platforms_to_run = list(AVAILABLE_PLATFORMS.keys())
    else:
        plat = args.platform.lower().strip()
        if plat not in AVAILABLE_PLATFORMS:
            available_list = ", ".join(AVAILABLE_PLATFORMS.keys())
            logger.error(f"Unknown platform '{plat}'. Currently available: {available_list}")
            sys.exit(1)
        platforms_to_run = [plat]

    run_platform(platforms_to_run)


if __name__ == "__main__":
    main()
