"""
cogs/poller.py — Discord Cog for the Upwork background polling loop.
"""

import asyncio
import hashlib
import urllib.parse
from datetime import datetime
import psutil
import discord
from discord.ext import commands, tasks

from config import TRACKED_URLS, POLL_INTERVAL_SECONDS
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from monitor import global_state
from logger import get_logger
from auth_manager import SessionExpiredError
from utils.formatter import format_job_message, format_thread_details, split_message

logger = get_logger(__name__)


async def send_with_retry(coro_func, *args, max_retries: int = 3, **kwargs):
    """
    Execute a Discord API coroutine with automatic retry on rate limiting.
    """
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after if hasattr(e, "retry_after") else 5.0
                logger.warning(
                    f"Discord 429 rate limit -- waiting {retry_after:.1f}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"Discord HTTP error {e.status}: {e.text}")
                return None
    logger.error("Max retries reached for Discord API call.")
    return None


class UpworkPoller(commands.Cog):
    def __init__(self, bot, scraper, auth_manager):
        self.bot = bot
        self.scraper = scraper
        self.auth_manager = auth_manager

    def cog_load(self):
        if not self.poll_upwork.is_running():
            self.poll_upwork.start()
        if not self.memory_monitor.is_running():
            self.memory_monitor.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_upwork.cancel()
        self.memory_monitor.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(minutes=30)
    async def memory_monitor(self):
        mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        global_state["memory_usage_mb"] = mem_mb
        if mem_mb > 400:
            logger.warning(f"⚠️ High memory usage: {mem_mb:.2f} MB")

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup...")
        # Since DB is synchronous, running it in async context is generally fine for small dbs,
        # but could block if large. Kept as is for compatibility.
        cleanup_old_jobs(14)

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_upwork(self):
        """
        Background task that polls Upwork for new jobs every N seconds.
        Iterates over all tracked URLs in config.json sequentially.
        """
        if not TRACKED_URLS:
            logger.error("No tracked_urls found in config.json")
            return

        total_new_count = 0

        # --- Proactive refresh (secondary safety net) ---
        if self.auth_manager.should_refresh():
            logger.info("🔄 Proactive session refresh (scheduled)")
            result = await asyncio.to_thread(
                self.auth_manager.refresh_session, reason="proactive scheduled refresh"
            )
            if result:
                auth_header, cookie_string = result
                self.scraper.update_session(auth_header, cookie_string)
                global_state["last_token_refresh"] = datetime.now().isoformat()

        for url_config in TRACKED_URLS:
            url_source = url_config["url"]
            channel_id = url_config["channel_id"]
            label = url_config["label"]

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except Exception as e:
                    logger.error(
                        f"Could not find channel {channel_id} for {label}: {e}"
                    )
                    global_state["errors_last_hour"] += 1
                    continue

            logger.info(f"🔍 Scanning: {label}")

            # Extract search query from the URL (q parameter)
            parsed_url = urllib.parse.urlparse(url_source)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            search_query = query_params.get("q", [""])[0]

            if not search_query:
                logger.warning(
                    f"No 'q' parameter found in {url_source}. Using label as fallback."
                )
                search_query = label

            # --- Fetch jobs with reactive refresh on 401/403 ---
            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query)
            except SessionExpiredError:
                logger.info(f"🔄 Reactive session refresh (401/403 for {label})")
                result = await asyncio.to_thread(
                    self.auth_manager.refresh_session,
                    reason="reactive refresh triggered by 401/403",
                )
                if result:
                    auth_header, cookie_string = result
                    self.scraper.update_session(auth_header, cookie_string)
                    global_state["last_token_refresh"] = datetime.now().isoformat()
                    try:
                        await asyncio.sleep(
                            2
                        )  # Give Cloudflare a moment to register the new clearance
                        jobs = await asyncio.to_thread(
                            self.scraper.fetch_jobs, search_query
                        )  # Retry once with fresh session
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
                if self.bot.is_closed():
                    break

                job_id = job.get("job_id", "")
                title = job.get("title", "Untitled")

                try:
                    description = job.get("description", "")
                    budget = job.get("budget", "")

                    # Compute current hash
                    hash_input = f"{title}|{description}|{budget}".encode("utf-8")
                    current_hash = hashlib.sha256(hash_input).hexdigest()

                    stored_hash = get_job_hash(job_id, url_source)

                    if stored_hash == current_hash:
                        # Skip if we've already seen this job and it hasn't changed
                        continue

                    if stored_hash == "":
                        # Legacy job (from before hash feature). Update hash silently and skip.
                        save_job(job, url_source, current_hash)
                        continue

                    is_updated = stored_hash is not None

                    # Fetch full details for this job BEFORE saving
                    ciphertext = job.get("ciphertext", "")
                    details = {}
                    if ciphertext:
                        try:
                            details = await asyncio.to_thread(
                                self.scraper.fetch_job_details, ciphertext
                            )
                        except SessionExpiredError:
                            logger.info(
                                "🔄 Reactive session refresh (401/403 on details)"
                            )
                            result = await asyncio.to_thread(
                                self.auth_manager.refresh_session,
                                reason="reactive refresh triggered by 401/403",
                            )
                            if result:
                                auth_header, cookie_string = result
                                self.scraper.update_session(auth_header, cookie_string)
                                global_state["last_token_refresh"] = (
                                    datetime.now().isoformat()
                                )
                                try:
                                    await asyncio.sleep(
                                        2
                                    )  # Give Cloudflare a moment to register the new clearance
                                    details = await asyncio.to_thread(
                                        self.scraper.fetch_job_details, ciphertext
                                    )  # Retry once
                                except SessionExpiredError:
                                    logger.warning("⚠️ Retry failed for job details")

                    # Save to database FIRST so we don't continuously fetch details for private jobs
                    save_job(job, url_source, current_hash)

                    # If the scraper returned the private flag, skip it!
                    if details.get("is_private_job"):
                        logger.info(f"🔒 Skipping private/restricted job: {title[:60]}")
                        continue

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    if is_updated:
                        logger.info(f"🔄 [UPDATED] {title[:60]}")
                    else:
                        logger.info(f"✨ [NEW] {title[:60]}")

                    # Format and send the main message
                    content_text, embed = format_job_message(
                        job, details, is_updated=is_updated
                    )
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
                        sent_message = await send_with_retry(
                            channel.send, content=content_text, embed=embed
                        )
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
                            parts = split_message(thread_text)
                            for part in parts:
                                await send_with_retry(thread.send, part)
                        else:
                            await send_with_retry(thread.send, thread_text)
                except Exception as e:
                    logger.error(
                        f"Exception raised while processing job {job_id} ({title}): {e}",
                        exc_info=True,
                    )
                    global_state["errors_last_hour"] += 1
                    continue

            if new_count > 0:
                logger.info(f"✅ {label}: Found {new_count} new jobs.")

            # Pause briefly before checking the next URL to avoid slamming the API
            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"📫 Cycle Complete: {total_new_count} posted | Total DB: {get_job_count()}"
            )

        # Refresh memory stats
        global_state["memory_usage_mb"] = psutil.Process().memory_info().rss / (
            1024 * 1024
        )

    @poll_upwork.before_loop
    async def before_poll(self):
        """Wait until the bot is fully ready before starting the poll loop."""
        await self.bot.wait_until_ready()


async def setup(bot, scraper, auth_manager):
    # Pass dependencies to the cog when adding it
    await bot.add_cog(UpworkPoller(bot, scraper, auth_manager))
