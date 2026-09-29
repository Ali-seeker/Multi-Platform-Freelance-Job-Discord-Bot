"""
facebook/formatter.py — Discord embed and thread formatting for Facebook group posts.
"""

from datetime import datetime
import discord
from utils.discord_helpers import parse_posted_time, split_message

FACEBOOK_BRAND_COLOR = 0x1877F2  # Facebook Blue


def format_facebook_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a Facebook group post notification.
    """
    title = job.get("title", "New Facebook Group Post")
    post_url = job.get("url", "https://www.facebook.com")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "")
    author = job.get("author", "Facebook Member")
    group_name = job.get("group_name", "Facebook Group")
    matched_query = query_label or job.get("query_label", "All Posts")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:350].strip()
    if len(description) > 350:
        desc_preview += "..."

    embed = discord.Embed(
        title=title,
        url=post_url,
        description=desc_preview if desc_preview else None,
        color=FACEBOOK_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Author", value=author, inline=True)
    embed.add_field(name="Group", value=group_name, inline=True)

    if matched_query and matched_query.lower() != "all posts":
        embed.add_field(name="Keyword", value=f"`{matched_query}`", inline=True)

    footer_text = f"Facebook Groups • {group_name}"
    embed.set_footer(text=footer_text)
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** Facebook post updated!" if is_updated else ""
    return content, embed


def format_facebook_thread_details(job: dict) -> str:
    """
    Builds detailed markdown content for the thread created under the post message.
    """
    title = job.get("title", "New Facebook Group Post")
    author = job.get("author", "Facebook Member")
    group_name = job.get("group_name", "Facebook Group")
    post_url = job.get("url", "https://www.facebook.com")
    description = job.get("description", "No description provided.")
    posted_time = job.get("posted_time", "Unknown")

    lines = [
        f"## 📱 {title}",
        f"**👤 Author:** {author}",
        f"**👥 Group:** {group_name}",
        f"**🕒 Posted:** {posted_time}",
        f"**🔗 Direct Post Link:** <{post_url}>",
        "",
        "### 📝 Full Post Content:",
        description,
        "",
        "---",
        "💡 *Tip: Click the link above to view or reply to this post directly on Facebook.*",
    ]
    return "\n".join(lines)
