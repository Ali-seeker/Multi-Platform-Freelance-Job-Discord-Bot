"""
workana/formatter.py — Discord embed and thread layout for Workana freelance projects.
"""

from datetime import datetime, timezone
import discord
from utils.discord_helpers import parse_posted_time, split_message

WORKANA_BRAND_COLOR = 0x00A5D6  # Workana Cyan/Blue


def format_workana_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a Workana job posting alert.
    """
    title = job.get("title", "Untitled Workana Project")
    job_url = job.get("url", "https://www.workana.com")
    budget = job.get("budget", "Negotiable")
    skills = job.get("skills", "")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "Recent")
    epoch_sec = job.get("epoch_sec", 0)
    client_name = job.get("client_name", "Workana Client")
    client_country = job.get("client_country", "International")
    client_rating = job.get("client_rating", "New Client")
    payment_verified = job.get("payment_verified", False)
    proposals_count = job.get("proposals_count", "0")
    matched_query = query_label or job.get("query_label", "Workana")

    if epoch_sec and epoch_sec > 0:
        posted_dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
        exact_posted = f"<t:{epoch_sec}:f>"
        rel_posted = f"<t:{epoch_sec}:R>"
    else:
        posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:350].strip()
    if len(description) > 350:
        desc_preview += "..."

    embed = discord.Embed(
        title=title[:256],
        url=job_url,
        description=desc_preview if desc_preview else None,
        color=WORKANA_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Budget", value=budget, inline=True)

    embed.add_field(name="Proposals", value=f"📥 {proposals_count}", inline=True)
    embed.add_field(name="Client", value=f"{client_name} ({client_country})", inline=True)
    embed.add_field(name="Payment", value="💳 Verified" if payment_verified else "⏳ Unverified", inline=True)

    if job.get("is_translated"):
        orig_lang = job.get("original_language", "Foreign")
        embed.add_field(name="Language", value=f"🌐 Translated ({orig_lang} ➔ English)", inline=True)

    if matched_query:
        embed.add_field(name="Keyword", value=f"`{matched_query}`", inline=True)

    if skills:
        embed.add_field(name="Skills", value=skills[:1024], inline=False)

    footer_text = f"Workana • {client_country}"
    if client_rating != "New Client":
        footer_text += f" • {client_rating}"
    embed.set_footer(text=footer_text[:2048])
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** Workana project updated!" if is_updated else ""
    return content, embed


def format_workana_thread_details(job: dict) -> str:
    """
    Builds a detailed Markdown message for the project's discussion thread.
    """
    title = job.get("title", "Untitled Workana Project")
    job_url = job.get("url", "https://www.workana.com")
    description = job.get("description", "No description provided.")
    budget = job.get("budget", "Negotiable")
    skills = job.get("skills", "None specified")
    posted_time = job.get("posted_time", "Recent")
    client_name = job.get("client_name", "Workana Client")
    client_country = job.get("client_country", "International")
    client_rating = job.get("client_rating", "New Client")
    payment_verified = job.get("payment_verified", False)
    proposals_count = job.get("proposals_count", "0")
    matched_query = job.get("query_label", "Workana")
    is_translated = job.get("is_translated", False)
    orig_lang = job.get("original_language", "original language")
    orig_desc = job.get("original_description", "")

    lines = [
        f"## 🌐 [{title}]({job_url})",
        "",
        f"**💰 Budget:** {budget}",
        f"**📥 Proposals Received:** {proposals_count}",
        f"**👤 Client:** {client_name} ({client_country})",
        f"**⭐ Client Rating:** {client_rating}",
        f"**💳 Payment Method:** {'✅ Verified' if payment_verified else '⚠️ Unverified'}",
        f"**🕒 Posted:** {posted_time}",
        f"**🏷️ Matched Keyword:** `{matched_query}`",
        f"**🛠️ Required Skills:** {skills}",
    ]

    if is_translated:
        lines.append(f"**🌐 Language:** Auto-translated from **{orig_lang}** to English")

    lines.extend([
        "",
        "### 📝 Full Project Description (English)",
        description,
    ])

    if is_translated and orig_desc and orig_desc != description:
        preview_orig = orig_desc[:1200].strip()
        if len(orig_desc) > 1200:
            preview_orig += "..."
        lines.extend([
            "",
            "---",
            f"### 🔤 Original Text ({orig_lang}):",
            f"> {preview_orig.replace(chr(10), chr(10) + '> ')}",
        ])

    lines.extend([
        "",
        "---",
        f"🔗 **[View Project & Submit Proposal on Workana]({job_url})**",
    ])
    return "\n".join(lines)
