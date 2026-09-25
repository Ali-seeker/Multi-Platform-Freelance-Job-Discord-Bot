"""
upwork/poller.py — Background polling loop for Upwork jobs.
Sends all scraped jobs to a single dedicated #upwork channel.
"""

import asyncio
import hashlib
import urllib.parse
from datetime import datetime
import psutil
import discord
from discord.ext import commands, tasks

from upwork.config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from upwork.scraper import UpworkScraper
from upwork.auth_manager import AuthManager, SessionExpiredError
from upwork.formatter import format_job_message, format_thread_details
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class UpworkPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: UpworkScraper = None, auth_manager: AuthManager = None):
        self.bot = bot
        self.scraper = scraper or UpworkScraper()
        self.auth_manager = auth_manager or AuthManager()
        self.channel: discord.TextChannel | None = None

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
        logger.info("🧹 Running daily DB cleanup for Upwork...")
        cleanup_old_jobs(days=14, platform="upwork")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #upwork channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="upwork",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_upwork(self):
        """
        Background task that polls Upwork for new jobs every N seconds.
        Sends all jobs matching any keyword into the single #upwork channel.
        """
        if not TRACKED_QUERIES:
            logger.warning("No tracked queries found in upwork/config.json")
            return

        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll Upwork: #upwork Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
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

        for query_config in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            url_source = query_config.get("url", "")
            search_query = query_config.get("query", "")
            label = query_config.get("label", search_query or "Upwork")

            if not search_query and url_source:
                if "upwork.com" in url_source:
                    parsed_url = urllib.parse.urlparse(url_source)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    search_query = query_params.get("q", [""])[0] or label
                else:
                    search_query = url_source

            if not search_query:
                search_query = label

            if not url_source:
                encoded = urllib.parse.quote(search_query)
                url_source = f"https://www.upwork.com/nx/search/jobs/?q={encoded}&sort=recency"

            logger.info(f"[UPWORK] [Step 1/5] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} jobs)...")

            # --- Fetch jobs with reactive refresh on 401/403 ---
            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except SessionExpiredError:
                logger.info(f"[UPWORK] 🔄 Reactive session refresh (401/403 encountered for '{label}')")
                result = await asyncio.to_thread(
                    self.auth_manager.refresh_session,
                    reason=f"reactive refresh triggered by 401/403 on {label}",
                )
                if result:
                    auth_header, cookie_string = result
                    self.scraper.update_session(auth_header, cookie_string)
                    global_state["last_token_refresh"] = datetime.now().isoformat()
                    try:
                        await asyncio.sleep(2)
                        jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
                    except SessionExpiredError:
                        logger.warning(f"[UPWORK] ⚠️ Retry failed (401/403) -- skipping '{label}'")
                        global_state["errors_last_hour"] += 1
                        continue
                else:
                    logger.error(f"[UPWORK] ❌ Session refresh failed -- skipping '{label}'")
                    global_state["errors_last_hour"] += 1
                    continue

            if not jobs:
                logger.info(f"[UPWORK] [Step 2/5] ℹ️ No jobs returned for '{label}'.")
                await asyncio.sleep(1)
                continue

            logger.info(f"[UPWORK] [Step 2/5] 🌐 Received {len(jobs)} jobs from Upwork GraphQL API")
            logger.info(f"[UPWORK] [Step 3/5] 🗄️ Checking {len(jobs)} jobs against 'upwork_jobs' table...")
            new_count = 0

            # Process jobs directly (private job checking with Selenium is removed)
            for job in jobs:
                if self.bot.is_closed():
                    break

                job_id = job.get("job_id", "")
                title = job.get("title", "Untitled")
                description = job.get("description", "")
                budget = job.get("budget", "")

                try:
                    # Content hash for update detection
                    hash_input = f"{title}|{description}|{budget}".encode("utf-8")
                    current_hash = hashlib.sha256(hash_input).hexdigest()

                    stored_hash = get_job_hash(job_id, url_source, platform="upwork")

                    if stored_hash == current_hash:
                        # Skip already seen identical job
                        continue

                    if stored_hash == "":
                        # Legacy job: update hash silently and skip
                        save_job(job, url_source, current_hash, platform="upwork")
                        continue

                    is_updated = stored_hash is not None
                    prefix = "🔄 [UPDATED]" if is_updated else "✨ [NEW]"

                    # Save to Upwork platform DB table FIRST
                    save_job(job, url_source, current_hash, platform="upwork")
                    logger.info(f"[UPWORK] [Step 4/5] 💾 {prefix} Saved to 'upwork_jobs': {job_id} | {title[:50]}")

                    # Fetch job details best-effort
                    ciphertext = job.get("ciphertext", "")
                    details = {}
                    if ciphertext:
                        try:
                            details = await asyncio.to_thread(
                                self.scraper.fetch_job_details, ciphertext
                            )
                        except Exception as e:
                            logger.debug(f"[UPWORK] Failed to fetch job details for {job_id}: {e}")
                            details = {}

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    # Format message with keyword tag
                    content_text, embed = format_job_message(
                        job, details, is_updated=is_updated, query_label=label
                    )
                    thread_name = f"Job: {title[:80]}"
                    thread = None

                    if isinstance(channel, discord.ForumChannel):
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
                            logger.error(f"[UPWORK] Failed to create forum thread: {e}")
                            global_state["errors_last_hour"] += 1
                            continue
                    else:
                        sent_message = await send_with_retry(
                            channel.send, content=content_text, embed=embed
                        )
                        if sent_message is None:
                            logger.error(f"[UPWORK] Failed to post job to #{channel.name}: {title[:40]}")
                            global_state["errors_last_hour"] += 1
                            continue

                        try:
                            thread = await send_with_retry(
                                sent_message.create_thread,
                                name=thread_name,
                                auto_archive_duration=60,
                            )
                        except Exception as e:
                            logger.debug(f"[UPWORK] Could not create thread for job {job_id}: {e}")

                    # Post detail thread messages
                    if thread:
                        thread_text = format_thread_details(details, job)
                        if len(thread_text) > 2000:
                            for part in split_message(thread_text):
                                await send_with_retry(thread.send, part)
                        else:
                            await send_with_retry(thread.send, thread_text)
                    logger.info(f"[UPWORK] [Step 5/5] 💬 Sent to #{channel.name} with details thread")

                except Exception as e:
                    logger.error(f"[UPWORK] Error processing job {job_id} ({title}): {e}", exc_info=True)
                    global_state["errors_last_hour"] += 1
                    continue

            if new_count > 0:
                logger.info(f"[UPWORK] ✅ Cycle complete for '{label}': {new_count} new jobs posted to #{channel.name}.")
            else:
                logger.info(f"[UPWORK] ⏭️ Cycle complete for '{label}': No new unposted jobs.")

            # Pause briefly between queries to avoid slamming API
            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"📫 Upwork Cycle Complete: {total_new_count} posted | Total Upwork DB: {get_job_count('upwork')}"
            )

        global_state["memory_usage_mb"] = psutil.Process().memory_info().rss / (1024 * 1024)

    @poll_upwork.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot, scraper=None, auth_manager=None):
    """Cog setup function."""
    await bot.add_cog(UpworkPoller(bot, scraper, auth_manager))
