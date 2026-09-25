"""
peopleperhour/formatter.py — Discord embed and thread formatting for PeoplePerHour jobs.
"""

from datetime import datetime
import discord
from utils.discord_helpers import parse_posted_time, split_message

PPH_BRAND_COLOR = 0xFF6200  # PeoplePerHour Brand Orange


def format_pph_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a PeoplePerHour job posting.
    """
    title = job.get("title", "Untitled Job")
    job_url = job.get("url", "https://www.peopleperhour.com")
    budget = job.get("budget", "Not specified")
    project_type = job.get("project_type", "Fixed Price")
    skills = job.get("skills", "")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "")
    proposal_count = job.get("proposal_count", "0")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:300].strip()
    if len(description) > 300:
        desc_preview += "..."

    embed = discord.Embed(
        title=title,
        url=job_url,
        description=desc_preview if desc_preview else None,
        color=PPH_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Budget", value=budget, inline=True)
    embed.add_field(name="Type", value=project_type, inline=True)
    embed.add_field(name="Proposals Received", value=proposal_count, inline=True)

    if query_label:
        embed.add_field(name="Keyword", value=f"`{query_label}`", inline=True)

    if skills:
        embed.add_field(name="Category / Skills", value=skills[:1024], inline=False)

    footer_text = f"PeoplePerHour • {query_label}" if query_label else "PeoplePerHour Job Alerts"
    embed.set_footer(text=footer_text)
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** This PeoplePerHour job was updated!" if is_updated else ""
    return content, embed


def format_pph_thread_details(job: dict) -> str:
    """
    Builds a detailed Markdown message for the job's discussion thread.
    """
    title = job.get("title", "Untitled Job")
    job_url = job.get("url", "https://www.peopleperhour.com")
    description = job.get("description", "No detailed description provided.")
    budget = job.get("budget", "Not specified")
    project_type = job.get("project_type", "Fixed Price")
    skills = job.get("skills", "None listed")
    posted_time = job.get("posted_time", "")
    proposal_count = job.get("proposal_count", "0")

    posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    lines = [
        "__**Full Job Description**__",
        "",
        description[:1500] + ("..." if len(description) > 1500 else ""),
        "",
        "__**Job Details**__",
        f"- **Budget:** {budget}",
        f"- **Type:** {project_type}",
        f"- **Posted Exact:** {exact_posted} ({rel_posted})",
        f"- **Proposals Received:** {proposal_count}",
    ]

    if skills:
        lines.append(f"- **Category / Skills:** {skills}")

    lines.append("")
    lines.append(f"**[View & Send Proposal on PeoplePerHour]({job_url})**")

    return "\n".join(lines)
