"""
utils/formatter.py — Message formatting utilities for the Discord Bot.
Extracts message design and embed logic away from the main bot logic.
"""

from datetime import datetime, timezone
import discord


def format_relative_time(iso_timestamp: str) -> str:
    """
    Convert an ISO 8601 timestamp to a human-readable relative time string.

    Examples:
        "2 minutes ago", "1 hour ago", "3 days ago"

    Args:
        iso_timestamp: ISO 8601 datetime string (e.g., "2026-07-17T06:14:13.856Z")

    Returns:
        Human-readable relative time, or "Unknown" if parsing fails.
    """
    if not iso_timestamp:
        return "Unknown"

    try:
        # Handle both "Z" suffix and "+00:00" timezone formats
        clean = iso_timestamp.replace("Z", "+00:00")
        posted = datetime.fromisoformat(clean)
        now = datetime.now(timezone.utc)
        diff = now - posted

        seconds = int(diff.total_seconds())
        if seconds < 0:
            return "Just now"
        if seconds < 60:
            return f"{seconds} seconds ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''} ago"
    except (ValueError, TypeError):
        return "Unknown"


def build_job_url(ciphertext: str) -> str:
    """
    Build the Upwork job URL from its ciphertext identifier.
    """
    return f"https://www.upwork.com/jobs/{ciphertext}"


def format_job_message(
    job: dict, details: dict = None, is_updated: bool = False
) -> tuple[str, discord.Embed]:
    """
    Build a formatted Discord message for a new Upwork job posting.

    The message includes the job title, relative posting time, budget,
    experience level, current time, proposal count, client info,
    a description preview, and an apply link.

    Args:
        job: Parsed job dictionary from parse_job() (Phase 1)
        details: Optional full details dictionary from fetch_job_details()

    Returns:
        A tuple of (content_text, embed) to send to Discord.
    """
    title = job.get("title", "Untitled Job")
    ciphertext = job.get("ciphertext", "")
    job_url = build_job_url(ciphertext) if ciphertext else ""
    posted_time = job.get("posted_time", "")
    budget = job.get("budget", "Not specified")
    skills = job.get("skills", "")
    description = job.get("description", "")
    experience_level = job.get("experience_level", "Not specified")

    # Relative time (e.g., "15 minutes ago")
    relative = format_relative_time(posted_time)

    # Current time in HH:MM 24-hour format
    current_time = datetime.now().strftime("%H:%M")

    # Description preview (first 300 chars, clean up)
    desc_preview = description[:300].strip()
    if len(description) > 300:
        desc_preview += "..."

    # Determine color based on experience level
    level_lower = experience_level.lower()
    if "entry" in level_lower:
        color = 0x2ECC71  # Green
    elif "intermediate" in level_lower:
        color = 0x3498DB  # Blue
    elif "expert" in level_lower:
        color = 0xF39C12  # Gold/Orange
    else:
        color = 0x2ECC71  # Default brand green

    # Initialize Embed
    embed = discord.Embed(
        title=title,
        url=job_url if job_url else None,
        description=desc_preview if desc_preview else None,
        color=color,
    )

    # Fields
    embed.add_field(name="Posted", value=relative, inline=True)
    embed.add_field(name="Budget/Rate", value=budget, inline=True)
    embed.add_field(name="Level", value=experience_level, inline=True)
    embed.add_field(name="Time", value=current_time, inline=True)

    if skills:
        embed.add_field(name="Skills", value=skills, inline=False)

    # Footer and Timestamp
    embed.set_footer(text="Upwork Job Bot")
    embed.timestamp = discord.utils.utcnow()

    content = (
        "🔄 **[UPDATED]** This job has been updated by the client!"
        if is_updated
        else ""
    )

    return content, embed


def format_thread_details(details: dict, job: dict) -> str:
    """
    Build a detailed message for the job thread with full information.
    """
    ciphertext = job.get("ciphertext", "")
    job_url = build_job_url(ciphertext) if ciphertext else ""

    # --- Full Job Description ---
    description = details.get("description") or job.get(
        "description", "No description available."
    )

    # --- Client Details ---
    location = details.get("client_location", "Unknown")
    member_since = details.get("client_member_since", "")
    if member_since:
        try:
            clean = member_since.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            member_since = dt.strftime("%b %Y")
        except (ValueError, TypeError):
            member_since = "Unknown"
    else:
        member_since = "Unknown"

    total_spent = details.get("client_total_spent", 0)
    spent_str = f"${total_spent:,.2f}" if total_spent else "$0"
    total_jobs = details.get("client_total_jobs", 0)
    hire_rate = details.get("client_hire_rate", 0)
    rating = details.get("client_rating", 0)
    rating_str = f"{rating}/5" if rating else "No rating"
    payment = "Verified" if details.get("payment_verified") else "Not Verified"

    # --- Job Details ---
    job_type = details.get("job_type") or job.get("job_type", "Not specified")
    budget = details.get("budget") or job.get("budget", "Not specified")
    duration = details.get("project_duration", "Not specified")
    level = details.get("experience_level") or job.get(
        "experience_level", "Not specified"
    )
    category = details.get("category", "Not specified")
    applicants = details.get("total_applicants", 0)
    hired = details.get("total_hired", 0)

    lines = []

    # Section 1: Full Description
    lines.append("__**Full Job Description**__")
    lines.append("")
    if len(description) > 1500:
        lines.append(description[:1500] + "...")
    else:
        lines.append(description)
    lines.append("")

    # Section 2: Client Details
    client_lines = []
    if location and location != "Unknown":
        client_lines.append(f"- **Location:** {location}")
    if member_since and member_since != "Unknown":
        client_lines.append(f"- **Member Since:** {member_since}")
    if total_spent > 0:
        client_lines.append(f"- **Total Spent:** {spent_str}")
    if total_jobs > 0:
        client_lines.append(f"- **Jobs Posted:** {total_jobs}")
        client_lines.append(f"- **Hire Rate:** {hire_rate}%")
    if rating:
        client_lines.append(f"- **Rating:** {rating_str}")
    if details and "payment_verified" in details:
        client_lines.append(f"- **Payment:** {payment}")

    if client_lines:
        lines.append("__**Client Details**__")
        lines.extend(client_lines)
        lines.append("")

    # Section 3: Job Details
    job_lines = []
    if job_type and job_type != "Not specified":
        job_lines.append(f"- **Type:** {job_type}")
    if budget and budget not in ("Not specified", "Budget not specified"):
        job_lines.append(f"- **Budget:** {budget}")
    if duration and duration != "Not specified":
        job_lines.append(f"- **Duration:** {duration}")
    if level and level != "Not specified":
        job_lines.append(f"- **Experience Level:** {level}")
    if category and category != "Not specified":
        job_lines.append(f"- **Category:** {category}")
    if details and "total_applicants" in details:
        job_lines.append(f"- **Proposals:** {applicants}")
    if details and "total_hired" in details:
        job_lines.append(f"- **Hired:** {hired}")

    if job_lines:
        lines.append("__**Job Details**__")
        lines.extend(job_lines)
        lines.append("")

    # Apply link
    if job_url:
        lines.append(f"**[Apply Here]({job_url})**")

    return "\n".join(lines)


def split_message(text: str, limit: int = 1900) -> list[str]:
    """
    Split a long message into chunks that fit Discord's 2000-char limit.
    Splits at newline boundaries to avoid cutting mid-sentence.
    """
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        parts.append(current)
    return parts
