"""
threads/poller.py — Background polling loop for Meta Threads posts.
Sends all scraped posts to a single dedicated #threads channel.
"""

import asyncio
import hashlib
import discord
from discord.ext import commands, tasks

from threads.config import (
    TRACKED_QUERIES,
    POLL_INTERVAL_SECONDS,
    JOBS_PER_PAGE,
    CHANNEL_ID,
    set_channel_id,
)
from threads.scraper import ThreadsScraper
from threads.formatter import (
    format_threads_job_message,
    format_threads_thread_details,
)
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from utils.translator import translate_job_to_english
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class ThreadsPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, scraper: ThreadsScraper = None):
        self.bot = bot
        self.scraper = scraper or ThreadsScraper()
        self.channel: discord.TextChannel | None = None

    def cog_load(self):
        if not self.poll_threads.is_running():
            self.poll_threads.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_threads.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for Threads...")
        cleanup_old_jobs(days=14, platform="threads")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #threads channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="threads",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_threads(self):
        """
        Background task that checks Threads for recent posts matching tracked queries.
        Sends all received posts into the single #threads channel.
        """
        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll Threads: #threads Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
            return

        total_new_count = 0

        for query_info in TRACKED_QUERIES:
            if self.bot.is_closed():
                break

            search_query = query_info["query"]
            url_source = query_info.get("url") or search_query
            label = query_info.get("label", search_query)

            logger.info(f"[THREADS] [Step 1/5] 🔍 Scanning query: '{label}' (Batch limit: {JOBS_PER_PAGE} posts)...")

            try:
                jobs = await asyncio.to_thread(self.scraper.fetch_jobs, search_query, JOBS_PER_PAGE)
            except Exception as e:
                logger.error(f"[THREADS] Error fetching Threads posts for '{label}': {e}")
                global_state["errors_last_hour"] += 1
                continue

            if not jobs:
                logger.info(f"[THREADS] [Step 2/5] ℹ️ No posts returned for '{label}'.")
                await asyncio.sleep(1)
                continue

            logger.info(f"[THREADS] [Step 2/5] 🌐 Received {len(jobs)} posts from Threads search")
            logger.info(f"[THREADS] [Step 3/5] 🗄️ Checking {len(jobs)} posts against 'threads_jobs' table...")
            new_count = 0

            for job in jobs:
                if self.bot.is_closed():
                    break

                job_id = job.get("job_id", "")
                title = job.get("title", "Untitled")
                description = job.get("description", "")

                try:
                    hash_input = f"{title}|{description}|{job_id}".encode("utf-8")
                    current_hash = hashlib.sha256(hash_input).hexdigest()

                    stored_hash = get_job_hash(job_id, url_source, platform="threads")

                    if stored_hash == current_hash:
                        continue

                    if stored_hash == "":
                        save_job(job, url_source, current_hash, platform="threads")
                        continue

                    is_updated = stored_hash is not None
                    prefix = "🔄 [UPDATED]" if is_updated else "✨ [NEW]"

                    # Save to [threads_jobs] table in SQLite
                    save_job(job, url_source, current_hash, platform="threads")
                    logger.info(f"[THREADS] [Step 4/5] 💾 {prefix} Saved to 'threads_jobs': {job_id} | {title[:50]}")

                    new_count += 1
                    total_new_count += 1
                    global_state["jobs_posted_last_hour"] += 1

                    # Auto-translate foreign language posts to English
                    job = await asyncio.to_thread(translate_job_to_english, job)

                    content_text, embed = format_threads_job_message(
                        job, is_updated=is_updated, query_label=label
                    )
                    thread_name = f"Threads: {job.get('title', title)[:80]}"
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
                            logger.error(f"[THREADS] Failed to create forum thread: {e}")
                            global_state["errors_last_hour"] += 1
                            continue
                    else:
                        sent_message = await send_with_retry(
                            channel.send, content=content_text if content_text else None, embed=embed
                        )
                        if sent_message is None:
                            logger.error(f"[THREADS] Failed to post to #{channel.name}: {title[:40]}")
                            global_state["errors_last_hour"] += 1
                            continue

                        try:
                            thread = await send_with_retry(
                                sent_message.create_thread,
                                name=thread_name,
                                auto_archive_duration=60,
                            )
                        except Exception as e:
                            logger.debug(f"[THREADS] Could not create thread for post {job_id}: {e}")

                    if thread:
                        thread_text = format_threads_thread_details(job)
                        chunks = split_message(thread_text, 1900)
                        for chunk in chunks:
                            await send_with_retry(thread.send, content=chunk)

                    logger.info(f"[THREADS] [Step 5/5] 💬 Sent to #{channel.name} with details thread")

                except Exception as e:
                    logger.error(f"[THREADS] Error processing post {job_id}: {e}", exc_info=True)
                    global_state["errors_last_hour"] += 1
                    continue

                await asyncio.sleep(0.5)

            if new_count > 0:
                logger.info(
                    f"[THREADS] ✅ Cycle complete for '{label}': {new_count} new posts posted to #{channel.name}."
                )
            else:
                logger.info(f"[THREADS] ⏭️ Cycle complete for '{label}': No new unposted posts.")

            await asyncio.sleep(2)

        if total_new_count > 0:
            logger.info(
                f"[THREADS] 📫 All queries complete: {total_new_count} total new posts posted. Total DB: {get_job_count('threads')}"
            )
        else:
            logger.info("[THREADS] ⏭️ All queries complete: No new unposted Threads posts found.")

    @poll_threads.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @poll_threads.error
    async def on_poll_threads_error(self, error):
        logger.error(f"[THREADS] 💥 Unhandled error in poll_threads loop: {error}", exc_info=True)
