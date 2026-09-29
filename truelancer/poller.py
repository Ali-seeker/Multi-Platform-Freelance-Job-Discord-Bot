"""
truelancer/poller.py — Background polling loop for Truelancer jobs.
Sends all scraped jobs to a single dedicated #truelancer channel.
"""

import asyncio
import hashlib
import re
import discord
from discord.ext import commands, tasks

from truelancer.config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from truelancer.scraper import TruelancerScraper
from truelancer.formatter import (
    format_truelancer_job_message,
    format_truelancer_thread_details,
)
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class TruelancerPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: TruelancerScraper = None):
        self.bot = bot
        self.scraper = scraper or TruelancerScraper()
        self.channel: discord.TextChannel | None = None

    def cog_load(self):
        if not self.poll_truelancer.is_running():
            self.poll_truelancer.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_truelancer.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for Truelancer...")
        cleanup_old_jobs(days=14, platform="truelancer")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #truelancer channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="truelancer",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_truelancer(self):
        """
        Background task that polls Truelancer for new jobs every N seconds.
        Sends all jobs matching any keyword into the single #truelancer channel.
        """
        if not TRACKED_QUERIES:
            logger.warning("No tracked queries found in truelancer/config.json")
            return

        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll Truelancer: #truelancer Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
            return

        total_new_count = 0

        for query_config in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            search_query = query_config.get("query", "")
            url_source = query_config.get("url", f"https://www.truelancer.com/freelance-jobs?q={search_query}")
            label = query_config.get("label", search_query or "Truelancer")

            logger.info(f"[TRUELANCER] [Step 1/5] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} jobs)...")

            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except Exception as e:
                logger.error(f"[TRUELANCER] Error fetching Truelancer jobs for '{label}': {e}")
                global_state["errors_last_hour"] += 1
                continue

            if not jobs:
                logger.info(f"[TRUELANCER] [Step 2/5] ℹ️ No jobs returned for '{label}'.")
                await asyncio.sleep(1)
                continue

            logger.info(f"[TRUELANCER] [Step 2/5] 🌐 Received {len(jobs)} jobs from Truelancer")
            logger.info(f"[TRUELANCER] [Step 3/5] 🗄️ Checking {len(jobs)} jobs against 'truelancer_jobs' table...")
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

                    stored_hash = get_job_hash(job_id, url_source, platform="truelancer")

                    if stored_hash is not None and stored_hash == current_hash:
                        continue

                    is_update = stored_hash is not None and stored_hash != current_hash
                    save_job(job, url_source, current_hash, platform="truelancer")
                    new_count += 1
                    total_new_count += 1

                    status_prefix = "🔄 [UPDATE]" if is_update else "✨ [NEW]"
                    logger.info(
                        f"[TRUELANCER] [Step 4/5] 💾 {status_prefix} Saved to 'truelancer_jobs': {job_id} | {title[:40]}"
                    )

                    content, embed = format_truelancer_job_message(
                        job=job,
                        is_updated=is_update,
                        query_label=label,
                    )

                    job_msg = None
                    if isinstance(channel, discord.ForumChannel):
                        try:
                            thread_title = f"{'🔄 ' if is_update else ''}{title}"[:100]
                            first_comment = format_truelancer_thread_details(job)
                            chunks = split_message(first_comment, 2000)
                            thread, job_msg = await channel.create_thread(
                                name=thread_title,
                                embed=embed,
                                content=content if content else None,
                            )
                            for chunk in chunks:
                                await thread.send(chunk)
                        except Exception as e:
                            logger.error(f"[TRUELANCER] Failed to create forum thread: {e}")
                    else:
                        job_msg = await send_with_retry(
                            channel.send,
                            content=content if content else None,
                            embed=embed,
                        )
                        if not job_msg:
                            logger.error(f"[TRUELANCER] Failed to post job to #{channel.name}: {title[:40]}")
                            continue

                        # Create detail thread under the job message
                        try:
                            thread_title = f"{'🔄 ' if is_update else ''}{title}"[:100]
                            thread = await job_msg.create_thread(
                                name=thread_title,
                                auto_archive_duration=1440,
                            )
                            full_details = format_truelancer_thread_details(job)
                            chunks = split_message(full_details, 2000)
                            for chunk in chunks:
                                await send_with_retry(thread.send, chunk)
                        except Exception as te:
                            logger.warning(f"[TRUELANCER] Could not create thread for '{title[:30]}': {te}")

                    logger.info(f"[TRUELANCER] [Step 5/5] 💬 Sent to #{channel.name} with details thread")

                except Exception as e:
                    logger.error(f"[TRUELANCER] Error processing job {job_id} ({title}): {e}", exc_info=True)
                    global_state["errors_last_hour"] += 1
                    continue

            if new_count > 0:
                logger.info(f"[TRUELANCER] ✅ Cycle complete for '{label}': {new_count} new jobs posted to #{channel.name}.")
            else:
                logger.info(f"[TRUELANCER] ⏭️ Cycle complete for '{label}': No new unposted jobs.")

            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"[TRUELANCER] 📫 Cycle complete: {total_new_count} posted | Total Truelancer DB: {get_job_count('truelancer')}"
            )

    @poll_truelancer.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @poll_truelancer.error
    async def on_poll_truelancer_error(self, error):
        logger.error(f"[TRUELANCER] 💥 Unhandled error in poll_truelancer loop: {error}", exc_info=True)


async def setup(bot: commands.Bot, scraper=None):
    await bot.add_cog(TruelancerPoller(bot, scraper))
