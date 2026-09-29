"""
facebook/poller.py — Background polling loop for Facebook group posts via email notifications.
Sends all parsed posts to a single dedicated #facebook channel.
"""

import asyncio
import hashlib
import discord
from discord.ext import commands, tasks

from facebook.config import (
    POLL_INTERVAL_SECONDS,
    CHANNEL_ID,
    set_channel_id,
    FB_EMAIL_USER,
)
from facebook.email_listener import FacebookEmailListener
from facebook.formatter import (
    format_facebook_job_message,
    format_facebook_thread_details,
)
from db import save_job, get_job_count, cleanup_old_jobs, get_job_hash
from utils.discord_helpers import send_with_retry, split_message, get_or_create_platform_channel
from monitor import global_state
from logger import get_logger

logger = get_logger(__name__)


class FacebookPoller(commands.Cog):
    def __init__(self, bot: commands.Bot, listener: FacebookEmailListener = None):
        self.bot = bot
        self.listener = listener or FacebookEmailListener()
        self.channel: discord.TextChannel | None = None
        self._warned_unconfigured = False

    def cog_load(self):
        if not self.poll_facebook.is_running():
            self.poll_facebook.start()
        if not self.db_cleanup_task.is_running():
            self.db_cleanup_task.start()

    def cog_unload(self):
        self.poll_facebook.cancel()
        self.db_cleanup_task.cancel()

    @tasks.loop(hours=24)
    async def db_cleanup_task(self):
        logger.info("🧹 Running daily DB cleanup for Facebook...")
        cleanup_old_jobs(days=14, platform="facebook")

    async def _resolve_channel(self) -> discord.TextChannel | None:
        """Resolves or creates the single dedicated #facebook channel."""
        if self.channel:
            return self.channel

        self.channel = await get_or_create_platform_channel(
            bot=self.bot,
            platform_name="facebook",
            preferred_channel_id=CHANNEL_ID,
            save_id_callback=set_channel_id,
        )
        return self.channel

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_facebook(self):
        """
        Background task that checks the email inbox for new Facebook group posts.
        Sends all received posts into the single #facebook channel.
        """
        if not self.listener.is_configured():
            if not self._warned_unconfigured:
                logger.warning(
                    "[FACEBOOK] ⚠️ FB_EMAIL_USER and FB_EMAIL_PASSWORD are not configured in .env. Waiting for configuration..."
                )
                self._warned_unconfigured = True
            return

        channel = await self._resolve_channel()
        if not channel:
            logger.error("Cannot poll Facebook: #facebook Discord channel could not be resolved or created.")
            global_state["errors_last_hour"] += 1
            return

        logger.info("[FACEBOOK] [Step 1/5] 📬 Checking inbox for new Facebook group notification emails...")

        try:
            posts = await asyncio.to_thread(self.listener.fetch_new_posts)
        except Exception as e:
            logger.error(f"[FACEBOOK] Error fetching notification emails: {e}")
            global_state["errors_last_hour"] += 1
            return

        if not posts:
            logger.info("[FACEBOOK] [Step 2/5] ℹ️ No new unread Facebook notification emails found.")
            return

        logger.info(f"[FACEBOOK] [Step 2/5] 🌐 Received {len(posts)} Facebook group post(s) from emails.")
        logger.info(f"[FACEBOOK] [Step 3/5] 🗄️ Checking {len(posts)} posts against 'facebook_jobs' table...")

        total_new_count = 0

        for post in posts:
            if self.bot.is_closed():
                break

            post_id = post.get("job_id", "")
            title = post.get("title", "Untitled")
            description = post.get("description", "")
            url_source = post.get("url", "https://www.facebook.com")
            matched_query = post.get("query_label", "All Posts")

            try:
                hash_input = f"{title}|{description}|{post_id}".encode("utf-8")
                current_hash = hashlib.sha256(hash_input).hexdigest()

                stored_hash = get_job_hash(post_id, url_source, platform="facebook")

                if stored_hash is not None and stored_hash == current_hash:
                    continue

                is_update = stored_hash is not None and stored_hash != current_hash
                save_job(post, url_source, current_hash, platform="facebook")
                total_new_count += 1

                status_prefix = "🔄 [UPDATE]" if is_update else "✨ [NEW]"
                logger.info(
                    f"[FACEBOOK] [Step 4/5] 💾 {status_prefix} Saved to 'facebook_jobs': {post_id} | {title[:40]}"
                )

                content, embed = format_facebook_job_message(
                    job=post,
                    is_updated=is_update,
                    query_label=matched_query,
                )

                job_msg = None
                if isinstance(channel, discord.ForumChannel):
                    try:
                        thread_title = f"{'🔄 ' if is_update else ''}{title}"[:100]
                        first_comment = format_facebook_thread_details(post)
                        chunks = split_message(first_comment, 2000)
                        thread, job_msg = await channel.create_thread(
                            name=thread_title,
                            embed=embed,
                            content=content if content else None,
                        )
                        for chunk in chunks:
                            await thread.send(chunk)
                    except Exception as e:
                        logger.error(f"[FACEBOOK] Failed to create forum thread: {e}")
                else:
                    job_msg = await send_with_retry(
                        channel.send,
                        content=content if content else None,
                        embed=embed,
                    )
                    if not job_msg:
                        logger.error(f"[FACEBOOK] Failed to post message to #{channel.name}: {title[:40]}")
                        continue

                    # Create detail thread under the job message
                    try:
                        thread_title = f"{'🔄 ' if is_update else ''}{title}"[:100]
                        thread = await job_msg.create_thread(
                            name=thread_title,
                            auto_archive_duration=1440,
                        )
                        full_details = format_facebook_thread_details(post)
                        chunks = split_message(full_details, 2000)
                        for chunk in chunks:
                            await send_with_retry(thread.send, chunk)
                    except Exception as te:
                        logger.warning(f"[FACEBOOK] Could not create thread for '{title[:30]}': {te}")

                logger.info(f"[FACEBOOK] [Step 5/5] 💬 Sent to #{channel.name} with details thread")

            except Exception as e:
                logger.error(f"[FACEBOOK] Error processing post {post_id} ({title}): {e}", exc_info=True)
                global_state["errors_last_hour"] += 1
                continue

        if total_new_count > 0:
            logger.info(
                f"[FACEBOOK] 📫 Cycle complete: {total_new_count} posted | Total Facebook DB: {get_job_count('facebook')}"
            )
        else:
            logger.info("[FACEBOOK] ⏭️ Cycle complete: No new unposted Facebook group posts.")

    @poll_facebook.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @poll_facebook.error
    async def on_poll_facebook_error(self, error):
        logger.error(f"[FACEBOOK] 💥 Unhandled error in poll_facebook loop: {error}", exc_info=True)


async def setup(bot: commands.Bot, listener=None):
    await bot.add_cog(FacebookPoller(bot, listener))
