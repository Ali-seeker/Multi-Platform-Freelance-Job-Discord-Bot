"""
threads/formatter.py — Discord embed and thread layout for Meta Threads posts.
"""

from datetime import datetime
import discord
from utils.discord_helpers import parse_posted_time, split_message

THREADS_BRAND_COLOR = 0x101010  # Threads Signature Dark Theme


def format_threads_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a Threads post alert.
    """
    title = job.get("title", "New Threads Post")
    post_url = job.get("url", "https://www.threads.net")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "")
    author = job.get("author", "Threads User")
    author_username = job.get("author_username", "threads_user")
    author_avatar = job.get("author_avatar", "")
    matched_query = query_label or job.get("query_label", "Threads")
    like_count = job.get("like_count")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:350].strip()
    if len(description) > 350:
        desc_preview += "..."

    embed = discord.Embed(
        title=title[:256],
        url=post_url,
        description=desc_preview if desc_preview else None,
        color=THREADS_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Author", value=author[:256], inline=True)

    if matched_query:
        embed.add_field(name="Keyword", value=f"`{matched_query}`", inline=True)

    if like_count is not None and like_count > 0:
        embed.add_field(name="Likes", value=f"❤️ {like_count:,}", inline=True)

    if author_avatar and author_avatar.startswith("http"):
        embed.set_thumbnail(url=author_avatar)

    footer_text = f"Threads • @{author_username}"
    embed.set_footer(text=footer_text[:2048])
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** Threads post updated!" if is_updated else ""
    return content, embed


def format_threads_thread_details(job: dict) -> str:
    """
    Builds detailed markdown content for the thread created under the post message.
    """
    title = job.get("title", "New Threads Post")
    author = job.get("author", "Threads User")
    post_url = job.get("url", "https://www.threads.net")
    description = job.get("description", "No description provided.")
    posted_time = job.get("posted_time", "Unknown")
    matched_query = job.get("query_label", "Threads")
    like_count = job.get("like_count")

    lines = [
        f"## 🧵 {title}",
        f"**👤 Author:** {author}",
        f"**🕒 Posted:** {posted_time}",
        f"**🔗 Direct Post Link:** <{post_url}>",
        f"**🏷️ Matched Keyword:** `{matched_query}`",
    ]

    if like_count is not None and like_count > 0:
        lines.append(f"**❤️ Likes:** {like_count:,}")

    lines.extend([
        "",
        "### 📝 Full Post Content:",
        description,
        "",
        "---",
        "💡 *Tip: Click the direct link above to view or reply to this post on Threads.*",
    ])
    return "\n".join(lines)
