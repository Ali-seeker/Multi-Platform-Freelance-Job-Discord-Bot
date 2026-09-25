"""
freelancer/poller.py — Background polling loop for Freelancer.com jobs.
Sends all scraped jobs to a single dedicated #freelancer channel.
"""

import asyncio
import hashlib
import discord
from discord.ext import commands, tasks

from freelancer.config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from freelancer.scraper import FreelancerScraper
from freelancer.formatter import (
    format_freelancer_job_message,
    format_freelancer_thread_details,
)
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class FreelancerPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: FreelancerScraper = None):
        self.bot = bot
        self.scraper = scraper or FreelancerScraper()
        self.channel: discord.TextChannel | None = None

    def cog_load(self):
        if not self.poll_freelancer.is_running():
            self.poll_freelancer.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_freelancer.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for Freelancer...")
        cleanup_old_jobs(days=14, platform="freelancer")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #freelancer channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="freelancer",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_freelancer(self):
        """
        Background task that polls Freelancer.com for new projects every N seconds.
        Sends all jobs matching any keyword into the single #freelancer channel.
        """
        if not TRACKED_QUERIES:
            logger.warning("No tracked queries found in freelancer/config.json")
            return

        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll Freelancer: #freelancer Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
            return

        total_new_count = 0

        for query_config in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            search_query = query_config.get("query", "")
            url_source = query_config.get("url", f"https://www.freelancer.com/jobs/?keyword={search_query}")
            label = query_config.get("label", search_query or "Freelancer")

            logger.info(f"[FREELANCER] [Step 1/5] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} jobs)...")

            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except Exception as e:
                logger.error(f"[FREELANCER] Error fetching Freelancer jobs for '{label}': {e}")
                global_state["errors_last_hour"] += 1
                continue

            if not jobs:
                logger.info(f"[FREELANCER] [Step 2/5] ℹ️ No jobs returned for '{label}'.")
                await asyncio.sleep(1)
                continue

            logger.info(f"[FREELANCER] [Step 2/5] 🌐 Received {len(jobs)} jobs from Freelancer REST API")
            logger.info(f"[FREELANCER] [Step 3/5] 🗄️ Checking {len(jobs)} jobs against 'freelancer_jobs' table...")
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

                    stored_hash = get_job_hash(job_id, url_source, platform="freelancer")

                    if stored_hash == current_hash:
                        continue

                    if stored_hash == "":
                        save_job(job, url_source, current_hash, platform="freelancer")
                        continue

                    is_updated = stored_hash is not None
                    prefix = "🔄 [UPDATED]" if is_updated else "✨ [NEW]"

                    # Save to freelancer_jobs table in SQLite
                    save_job(job, url_source, current_hash, platform="freelancer")
                    logger.info(f"[FREELANCER] [Step 4/5] 💾 {prefix} Saved to 'freelancer_jobs': {job_id} | {title[:50]}")

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    content_text, embed = format_freelancer_job_message(
                        job, is_updated=is_updated, query_label=label
                    )
                    thread_name = f"Freelancer: {title[:80]}"
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
                            logger.error(f"[FREELANCER] Failed to create forum thread: {e}")
                            global_state["errors_last_hour"] += 1
                            continue
                    else:
                        sent_message = await send_with_retry(
                            channel.send, content=content_text, embed=embed
                        )
                        if sent_message is None:
                            logger.error(f"[FREELANCER] Failed to post job to #{channel.name}: {title[:40]}")
                            global_state["errors_last_hour"] += 1
                            continue

                        try:
                            thread = await send_with_retry(
                                sent_message.create_thread,
                                name=thread_name,
                                auto_archive_duration=60,
                            )
                        except Exception as e:
                            logger.debug(f"[FREELANCER] Could not create thread for job {job_id}: {e}")

                    if thread:
                        thread_text = format_freelancer_thread_details(job)
                        if len(thread_text) > 2000:
                            for part in split_message(thread_text):
                                await send_with_retry(thread.send, part)
                        else:
                            await send_with_retry(thread.send, thread_text)
                    logger.info(f"[FREELANCER] [Step 5/5] 💬 Sent to #{channel.name} with details thread")

                except Exception as e:
                    logger.error(f"[FREELANCER] Error processing job {job_id} ({title}): {e}", exc_info=True)
                    global_state["errors_last_hour"] += 1
                    continue

            if new_count > 0:
                logger.info(f"[FREELANCER] ✅ Cycle complete for '{label}': {new_count} new jobs posted to #{channel.name}.")
            else:
                logger.info(f"[FREELANCER] ⏭️ Cycle complete for '{label}': No new unposted jobs.")

            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"[FREELANCER] 📫 Cycle complete: {total_new_count} posted | Total Freelancer DB: {get_job_count('freelancer')}"
            )

    @poll_freelancer.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot, scraper=None):
    await bot.add_cog(FreelancerPoller(bot, scraper))
