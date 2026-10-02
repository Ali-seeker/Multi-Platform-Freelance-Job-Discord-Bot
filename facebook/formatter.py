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
        title=title[:256],
        url=post_url,
        description=desc_preview if desc_preview else None,
        color=FACEBOOK_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Author", value=author[:256], inline=True)
    embed.add_field(name="Group", value=group_name[:256], inline=True)

    if matched_query and matched_query.lower() != "all posts":
        embed.add_field(name="Keyword", value=f"`{matched_query}`", inline=True)

    if job.get("is_translated"):
        orig_lang = job.get("original_language", "Foreign")
        embed.add_field(name="Language", value=f"🌐 Translated ({orig_lang})", inline=True)

    footer_text = f"Facebook Groups • {group_name}"
    embed.set_footer(text=footer_text[:2048])
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
    notif_body = job.get("notif_body", "")
    is_translated = job.get("is_translated", False)
    orig_lang = job.get("original_language", "original language")
    orig_desc = job.get("original_description", "")

    lines = [
        f"## 📱 {title}",
        f"**👤 Author:** {author}",
        f"**👥 Group:** {group_name}",
        f"**🕒 Posted:** {posted_time}",
        f"**🔗 Direct Post Link:** <{post_url}>",
    ]
    if notif_body and notif_body != title:
        lines.append(f"**🔔 Notification Alert:** {notif_body}")
    if is_translated:
        lines.append(f"**🌐 Translation:** Auto-translated from {orig_lang} to English")

    lines.extend([
        "",
        "### 📝 Full Post Content & Description (English):",
        description,
    ])

    if is_translated and orig_desc and orig_desc != description:
        preview_orig = orig_desc[:1200].strip()
        if len(orig_desc) > 1200:
            preview_orig += "..."
        lines.extend([
            "",
            f"### 🔤 Original Text ({orig_lang}):",
            preview_orig,
        ])

    lines.extend([
        "",
        "---",
        "💡 *Tip: Click the link above to view or reply to this post directly on Facebook.*",
    ])
    return "\n".join(lines)
