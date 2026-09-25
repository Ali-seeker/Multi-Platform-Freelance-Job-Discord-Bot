"""
freelancer/formatter.py — Discord embed and thread formatting for Freelancer.com projects.
"""

from datetime import datetime
import discord
from utils.discord_helpers import parse_posted_time, split_message

FREELANCER_BRAND_COLOR = 0x29B2FE  # Freelancer.com Blue


def format_freelancer_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a Freelancer.com project posting.
    """
    title = job.get("title", "Untitled Project")
    job_url = job.get("url", "https://www.freelancer.com")
    budget = job.get("budget", "Not specified")
    project_type = job.get("project_type", "Fixed Price")
    skills = job.get("skills", "")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "")
    bids_count = job.get("bids_count", "0")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:300].strip()
    if len(description) > 300:
        desc_preview += "..."

    embed = discord.Embed(
        title=title,
        url=job_url,
        description=desc_preview if desc_preview else None,
        color=FREELANCER_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Budget", value=budget, inline=True)
    embed.add_field(name="Type", value=project_type, inline=True)
    embed.add_field(name="Bids Received", value=bids_count, inline=True)

    if query_label:
        embed.add_field(name="Keyword", value=f"`{query_label}`", inline=True)

    if skills:
        embed.add_field(name="Skills", value=skills[:1024], inline=False)

    footer_text = f"Freelancer • {query_label}" if query_label else "Freelancer Job Alerts"
    embed.set_footer(text=footer_text)
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** This Freelancer project was updated!" if is_updated else ""
    return content, embed


def format_freelancer_thread_details(job: dict) -> str:
    """
    Builds a detailed Markdown message for the project's discussion thread.
    """
    title = job.get("title", "Untitled Project")
    job_url = job.get("url", "https://www.freelancer.com")
    description = job.get("description", "No detailed description provided.")
    budget = job.get("budget", "Not specified")
    project_type = job.get("project_type", "Fixed Price")
    skills = job.get("skills", "None listed")
    posted_time = job.get("posted_time", "")
    bids_count = job.get("bids_count", "0")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    lines = [
        "__**Full Project Description**__",
        "",
        description[:1500] + ("..." if len(description) > 1500 else ""),
        "",
        "__**Project Details**__",
        f"- **Budget:** {budget}",
        f"- **Type:** {project_type}",
        f"- **Posted Exact:** {exact_posted} ({rel_posted})",
        f"- **Bids Received:** {bids_count}",
    ]

    if skills:
        lines.append(f"- **Skills Required:** {skills}")

    lines.append("")
    lines.append(f"**[View & Bid on Freelancer]({job_url})**")

    return "\n".join(lines)
