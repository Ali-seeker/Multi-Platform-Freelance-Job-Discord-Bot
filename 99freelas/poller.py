"""
99freelas/poller.py — Background polling loop for 99freelas jobs.
Sends all scraped jobs to a single dedicated #99freelas channel.
"""

import asyncio
import hashlib
import discord
from discord.ext import commands, tasks

from .config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from .scraper import Freelance99Scraper
from .formatter import format_99freelas_job_message, format_99freelas_thread_details
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from utils.translator import translate_job_to_english
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class Freelance99Poller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: Freelance99Scraper = None):
        self.bot = bot
        self.scraper = scraper or Freelance99Scraper()
        self.channel: discord.TextChannel | None = None

    def cog_load(self):
        if not self.poll_99freelas.is_running():
            self.poll_99freelas.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_99freelas.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for 99freelas...")
        cleanup_old_jobs(days=14, platform="99freelas")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #99freelas channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="99freelas",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_99freelas(self):
        """
        Background task that polls 99freelas for new projects every N seconds.
        Sends all jobs matching any tracked keyword into the single #99freelas channel.
        """
        if not TRACKED_QUERIES:
            logger.warning("No tracked queries found in 99freelas/config.json")
            return

        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll 99freelas: #99freelas Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
            return

        total_new_count = 0

        for query_config in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            search_query = query_config.get("query", "")
            url_source = query_config.get("url", f"https://www.99freelas.com.br/projects?q={search_query}")
            label = query_config.get("label", search_query or "99freelas")

            logger.info(f"[99FREELAS] [Step 1/5] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} jobs)...")

            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except Exception as e:
                logger.error(f"[99FREELAS] Error fetching 99freelas jobs for '{label}': {e}")
                global_state["errors_last_hour"] += 1
                continue

            if not jobs:
                logger.info(f"[99FREELAS] [Step 2/5] ℹ️ No jobs returned for '{label}'.")
                await asyncio.sleep(1)
                continue

            logger.info(f"[99FREELAS] [Step 2/5] 🌐 Scraped {len(jobs)} projects from 99freelas search")
            logger.info(f"[99FREELAS] [Step 3/5] 🗄️ Checking {len(jobs)} projects against '99freelas_jobs' table...")
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

                    stored_hash = get_job_hash(job_id, url_source, platform="99freelas")

                    if stored_hash == current_hash:
                        continue

                    if stored_hash == "":
                        save_job(job, url_source, current_hash, platform="99freelas")
                        continue

                    is_updated = stored_hash is not None
                    prefix = "🔄 [UPDATED]" if is_updated else "✨ [NEW]"

                    # Save to [99freelas_jobs] table in SQLite
                    save_job(job, url_source, current_hash, platform="99freelas")
                    logger.info(f"[99FREELAS] [Step 4/5] 💾 {prefix} Saved to '99freelas_jobs': {job_id} | {title[:50]}")

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    # Auto-translate foreign language content (e.g. Portuguese to English)
                    job = await asyncio.to_thread(translate_job_to_english, job)

                    content_text, embed = format_99freelas_job_message(
                        job, is_updated=is_updated, query_label=label
                    )
                    thread_name = f"99freelas: {job.get('title', title)[:80]}"
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
                            logger.error(f"[99FREELAS] Failed to create forum thread: {e}")
                            global_state["errors_last_hour"] += 1
                            continue
                    else:
                        sent_message = await send_with_retry(
                            channel.send, content=content_text, embed=embed
                        )
                        if sent_message is None:
                            logger.error(f"[99FREELAS] Failed to post job to #{channel.name}: {title[:40]}")
                            global_state["errors_last_hour"] += 1
                            continue

                        try:
                            thread = await send_with_retry(
                                sent_message.create_thread,
                                name=thread_name,
                                auto_archive_duration=60,
                            )
                        except Exception as e:
                            logger.debug(f"[99FREELAS] Could not create thread for job {job_id}: {e}")

                    if thread:
                        thread_text = format_99freelas_thread_details(job)
                        if len(thread_text) > 2000:
                            for part in split_message(thread_text):
                                await send_with_retry(thread.send, part)
                        else:
                            await send_with_retry(thread.send, thread_text)
                    logger.info(f"[99FREELAS] [Step 5/5] 💬 Sent to #{channel.name} with details thread")

                except Exception as e:
                    logger.error(f"[99FREELAS] Error processing job {job_id} ({title}): {e}", exc_info=True)
                    global_state["errors_last_hour"] += 1
                    continue

            if new_count > 0:
                logger.info(f"[99FREELAS] ✅ Cycle complete for '{label}': {new_count} new jobs posted to #{channel.name}.")
            else:
                logger.info(f"[99FREELAS] ⏭️ Cycle complete for '{label}': No new unposted jobs.")

            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"[99FREELAS] 📊 Summary: {total_new_count} new 99freelas jobs posted this cycle. "
                f"Total in DB: {get_job_count(platform='99freelas')}"
            )
