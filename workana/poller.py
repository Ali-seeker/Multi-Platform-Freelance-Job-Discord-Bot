"""
workana/poller.py — Background polling loop for Workana projects.
Sends all scraped jobs to a single dedicated #workana channel.
"""

import asyncio
import hashlib
import discord
from discord.ext import commands, tasks

from workana.config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from workana.scraper import WorkanaScraper
from workana.formatter import format_workana_job_message, format_workana_thread_details
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from utils.translator import translate_job_to_english
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class WorkanaPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: WorkanaScraper = None):
        self.bot = bot
        self.scraper = scraper or WorkanaScraper()
        self.channel: discord.TextChannel | None = None

    def cog_load(self):
        if not self.poll_workana.is_running():
            self.poll_workana.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_workana.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for Workana...")
        cleanup_old_jobs(days=14, platform="workana")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #workana channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="workana",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_workana(self):
        channel = await self._resolve_channel()
        if channel is None:
            logger.warning("[WORKANA] Cannot poll: single #workana channel not resolved yet.")
            return

        total_queries = len(TRACKED_QUERIES)
        logger.info(
            f"[WORKANA] 🚀 Starting poll cycle across {total_queries} queries (Channel: #{channel.name})"
        )

        total_new_count = 0

        for query_config in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            search_query = query_config.get("query", "")
            url_source = query_config.get("url", f"https://www.workana.com/jobs?query={search_query}&format=json")
            label = query_config.get("label", search_query or "Workana")

            logger.info(f"[WORKANA] [Step 1/5] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} jobs)...")

            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except Exception as e:
                logger.error(f"[WORKANA] Error fetching Workana jobs for '{label}': {e}")
                global_state["errors_last_hour"] += 1
                continue

            if not jobs:
                logger.info(f"[WORKANA] [Step 2/5] ℹ️ No jobs returned for '{label}'.")
                await asyncio.sleep(1)
                continue

            logger.info(f"[WORKANA] [Step 2/5] 🌐 Received {len(jobs)} projects from Workana search")
            logger.info(f"[WORKANA] [Step 3/5] 🗄️ Checking {len(jobs)} projects against 'workana_jobs' table...")
            new_count = 0

            for job in jobs:
                if self.bot.is_closed():
                    break

                job_id = job.get("job_id", "")
                title = job.get("title", "Untitled")
                description = job.get("description", "")
                budget = job.get("budget", "")

                try:
                    hash_input = f"{title}|{description}|{budget}".encode("utf-8")
                    current_hash = hashlib.sha256(hash_input).hexdigest()

                    stored_hash = get_job_hash(job_id, url_source, platform="workana")

                    if stored_hash == current_hash:
                        continue

                    if stored_hash == "":
                        save_job(job, url_source, current_hash, platform="workana")
                        continue

                    # Auto-translate foreign projects (e.g. Spanish/Portuguese to English)
                    job = await asyncio.to_thread(translate_job_to_english, job)

                    is_updated = stored_hash is not None
                    prefix = "🔄 [UPDATED]" if is_updated else "✨ [NEW]"

                    # Save to [workana_jobs] table in SQLite
                    save_job(job, url_source, current_hash, platform="workana")
                    logger.info(f"[WORKANA] [Step 4/5] 💾 {prefix} Saved to 'workana_jobs': {job_id} | {title[:50]}")

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    content_text, embed = format_workana_job_message(
                        job, is_updated=is_updated, query_label=label
                    )
                    thread_name = f"Workana: {job.get('title', title)[:80]}"
                    thread = None

                    if isinstance(channel, discord.ForumChannel):
                        try:
                            thread_with_msg = await send_with_retry(
                                channel.create_thread,
                                name=thread_name,
                                content=content_text if content_text else None,
                                embed=embed,
                                auto_archive_duration=60,
                            )
                            if thread_with_msg:
                                thread = thread_with_msg.thread
                        except Exception as e:
                            logger.error(f"[WORKANA] Failed to create forum thread: {e}")
                            global_state["errors_last_hour"] += 1
                            continue
                    else:
                        sent_message = await send_with_retry(
                            channel.send, content=content_text if content_text else None, embed=embed
                        )
                        if sent_message is None:
                            logger.error(f"[WORKANA] Failed to post to #{channel.name}: {title[:40]}")
                            global_state["errors_last_hour"] += 1
                            continue

                        # Create detail thread under the sent message
                        try:
                            thread = await send_with_retry(
                                sent_message.create_thread,
                                name=thread_name,
                                auto_archive_duration=60,
                            )
                        except Exception as e:
                            logger.warning(f"[WORKANA] Could not create thread for '{title[:30]}': {e}")
                            thread = None

                    # Post detailed breakdown into the thread
                    if thread:
                        try:
                            thread_content = format_workana_thread_details(job)
                            chunks = split_message(thread_content, 1900)
                            for chunk in chunks:
                                await send_with_retry(thread.send, content=chunk)
                            logger.info(f"[WORKANA] [Step 5/5] 🧵 Thread created & details posted: '{thread.name}'")
                        except Exception as e:
                            logger.error(f"[WORKANA] Error posting details to thread: {e}")
                            global_state["errors_last_hour"] += 1
                    else:
                        logger.info(f"[WORKANA] [Step 5/5] 📢 Message posted to #{channel.name} (Thread skipped)")

                except Exception as e:
                    logger.error(f"[WORKANA] Error processing project {job_id}: {e}")
                    global_state["errors_last_hour"] += 1

                await asyncio.sleep(1.5)

            logger.info(f"[WORKANA] Finished query '{label}'. New projects posted: {new_count}")
            await asyncio.sleep(2)

        try:
            total_db_count = get_job_count(platform="workana")
        except Exception:
            total_db_count = "N/A"

        logger.info(
            f"[WORKANA] ✅ Cycle complete. Posted: {total_new_count} projects | Total in DB: {total_db_count}"
        )

    @poll_workana.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()
        logger.info("⏳ Workana poller ready. Starting loop...")
