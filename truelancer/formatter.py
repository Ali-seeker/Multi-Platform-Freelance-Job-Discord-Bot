"""
truelancer/formatter.py — Discord embed and thread formatting for Truelancer projects.
"""

from datetime import datetime
import discord
from utils.discord_helpers import parse_posted_time, split_message

TRUELANCER_BRAND_COLOR = 0x36C5F0  # Truelancer Sky Blue


def format_truelancer_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a Truelancer project posting.
    """
    title = job.get("title", "Untitled Project")
    job_url = job.get("url", "https://www.truelancer.com")
    budget = job.get("budget", "Not specified")
    project_type = job.get("project_type", "Fixed Price")
    skills = job.get("skills", "")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "")
    proposals_count = job.get("proposal_count", "0")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:300].strip()
    if len(description) > 300:
        desc_preview += "..."

    embed = discord.Embed(
        title=title,
        url=job_url,
        description=desc_preview if desc_preview else None,
        color=TRUELANCER_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Budget", value=budget, inline=True)
    embed.add_field(name="Type", value=project_type, inline=True)
    embed.add_field(name="Proposals", value=proposals_count, inline=True)

    if query_label:
        embed.add_field(name="Keyword", value=f"`{query_label}`", inline=True)

    if skills:
        embed.add_field(name="Skills", value=skills[:1024], inline=False)

    footer_text = f"Truelancer • {query_label}" if query_label else "Truelancer Job Alerts"
    embed.set_footer(text=footer_text)
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** This Truelancer project was updated!" if is_updated else ""
    return content, embed


def format_truelancer_thread_details(job: dict) -> str:
    """
    Builds the detailed discussion thread text for a Truelancer project.
    """
    title = job.get("title", "Untitled Project")
    job_url = job.get("url", "https://www.truelancer.com")
    budget = job.get("budget", "Not specified")
    project_type = job.get("project_type", "Fixed Price")
    skills = job.get("skills", "")
    description = job.get("description", "No description provided.")
    posted_time = job.get("posted_time", "")
    proposals_count = job.get("proposal_count", "0")

    _, exact_posted, rel_posted = parse_posted_time(posted_time)

    parts = [
        f"## 📋 [{title}]({job_url})",
        "",
        "### 💰 Project Overview",
        f"- **Budget:** {budget}",
        f"- **Project Type:** {project_type}",
        f"- **Proposals Received:** {proposals_count}",
        f"- **Posted Exact:** {exact_posted} ({rel_posted})",
        f"- **Apply Directly:** [Open on Truelancer]({job_url})",
    ]

    if skills:
        parts.extend(["", "### 🛠️ Required Skills", f"`{skills}`"])

    parts.extend(["", "### 📝 Full Description", description])

    return "\n".join(parts)
