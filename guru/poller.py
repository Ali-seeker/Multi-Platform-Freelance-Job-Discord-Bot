"""
guru/poller.py — Background polling loop for Guru jobs.
Sends all scraped jobs to a single dedicated #guru channel.
"""

import asyncio
import hashlib
import discord
from discord.ext import commands, tasks

from guru.config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from guru.scraper import GuruScraper
from guru.formatter import format_guru_job_message, format_guru_thread_details
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class GuruPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: GuruScraper = None):
        self.bot = bot
        self.scraper = scraper or GuruScraper()
        self.channel: discord.TextChannel | None = None

    def cog_load(self):
        if not self.poll_guru.is_running():
            self.poll_guru.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_guru.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for Guru...")
        cleanup_old_jobs(days=14, platform="guru")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #guru channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="guru",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_guru(self):
        """
        Background task that polls Guru for new jobs every N seconds.
        Sends all jobs matching any keyword into the single #guru channel.
        """
        if not TRACKED_QUERIES:
            logger.warning("No tracked queries found in guru/config.json")
            return

        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll Guru: #guru Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
            return

        total_new_count = 0

        for query_config in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            search_query = query_config.get("query", "")
            url_source = query_config.get("url", f"https://www.guru.com/d/jobs/?q={search_query}")
            label = query_config.get("label", search_query or "Guru")

            logger.info(f"[GURU] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} jobs)")

            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except Exception as e:
                logger.error(f"[GURU] Error fetching Guru jobs for '{label}': {e}")
                global_state["errors_last_hour"] += 1
                continue

            if not jobs:
                await asyncio.sleep(1)
                continue

            logger.info(f"[GURU] 🗄️ Checking {len(jobs)} jobs against 'guru_jobs' table...")
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

                    stored_hash = get_job_hash(job_id, url_source, platform="guru")

                    if stored_hash == current_hash:
                        continue

                    if stored_hash == "":
                        save_job(job, url_source, current_hash, platform="guru")
                        continue

                    is_updated = stored_hash is not None

                    # Save to guru_jobs table in SQLite
                    save_job(job, url_source, current_hash, platform="guru")
                    logger.info(f"[GURU] 💾 Saved to 'guru_jobs': {title[:50]}")

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    prefix = "🔄 [UPDATED]" if is_updated else "✨ [NEW]"
                    logger.info(f"[GURU] {prefix} ({label}) {title[:60]}")

                    content_text, embed = format_guru_job_message(
                        job, is_updated=is_updated, query_label=label
                    )
                    thread_name = f"Guru: {title[:80]}"
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
                            logger.error(f"[GURU] Failed to create forum thread: {e}")
                            global_state["errors_last_hour"] += 1
                            continue
                    else:
                        sent_message = await send_with_retry(
                            channel.send, content=content_text, embed=embed
                        )
                        if sent_message is None:
                            logger.error(f"[GURU] Failed to post job to #{channel.name}: {title[:40]}")
                            global_state["errors_last_hour"] += 1
                            continue

                        try:
                            thread = await send_with_retry(
                                sent_message.create_thread,
                                name=thread_name,
                                auto_archive_duration=60,
                            )
                        except Exception as e:
                            logger.debug(f"[GURU] Could not create thread for job {job_id}: {e}")

                    if thread:
                        thread_text = format_guru_thread_details(job)
                        if len(thread_text) > 2000:
                            for part in split_message(thread_text):
                                await send_with_retry(thread.send, part)
                        else:
                            await send_with_retry(thread.send, thread_text)
                    logger.info(f"[GURU] 💬 Successfully sent to #{channel.name}")

                except Exception as e:
                    logger.error(f"[GURU] Error processing job {job_id} ({title}): {e}", exc_info=True)
                    global_state["errors_last_hour"] += 1
                    continue

            if new_count > 0:
                logger.info(f"[GURU] ✅ {label}: Posted {new_count} new jobs to #{channel.name}.")

            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"[GURU] 📫 Cycle complete: {total_new_count} posted | Total Guru DB: {get_job_count('guru')}"
            )

    @poll_guru.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot, scraper=None):
    await bot.add_cog(GuruPoller(bot, scraper))
