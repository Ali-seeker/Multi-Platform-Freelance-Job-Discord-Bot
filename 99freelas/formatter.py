"""
99freelas/formatter.py — Discord embed and thread formatting for 99freelas jobs.
"""

from datetime import datetime, timezone
import discord
from utils.discord_helpers import parse_posted_time, split_message

FREELAS99_BRAND_COLOR = 0x00B074  # 99freelas Emerald Green


def format_99freelas_job_message(
    job: dict, is_updated: bool = False, query_label: str = ""
) -> tuple[str, discord.Embed]:
    """
    Builds a formatted Discord embed for a 99freelas job posting.
    """
    title = job.get("title", "Untitled Job")
    job_url = job.get("url", "https://www.99freelas.com.br")
    budget = job.get("budget", "A combinar / Por proposta")
    skills = job.get("skills", "")
    description = job.get("description", "")
    posted_time = job.get("posted_time", "")
    epoch_sec = job.get("epoch_sec", 0)
    experience_level = job.get("experience_level", "Não especificado")
    proposals_count = job.get("proposals_count", "0")
    client_name = job.get("client_name", "Anônimo")

    if epoch_sec and epoch_sec > 0:
        posted_dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
        exact_posted = f"<t:{epoch_sec}:f>"
        rel_posted = f"<t:{epoch_sec}:R>"
    else:
        posted_dt, exact_posted, rel_posted = parse_posted_time(posted_time)

    desc_preview = description[:300].strip()
    if len(description) > 300:
        desc_preview += "..."

    embed = discord.Embed(
        title=title,
        url=job_url,
        description=desc_preview if desc_preview else None,
        color=FREELAS99_BRAND_COLOR,
    )

    embed.add_field(name="Exact Posted", value=exact_posted, inline=True)
    embed.add_field(name="Relative", value=rel_posted, inline=True)
    embed.add_field(name="Budget / Preço", value=budget, inline=True)
    embed.add_field(name="Propostas", value=f"📥 {proposals_count}", inline=True)
    embed.add_field(name="Nível", value=experience_level, inline=True)

    if job.get("is_translated"):
        orig_lang = job.get("original_language", "Portuguese")
        embed.add_field(name="Language", value=f"🌐 Translated ({orig_lang} ➔ English)", inline=True)

    if query_label:
        embed.add_field(name="Keyword", value=f"`{query_label}`", inline=True)

    if client_name:
        embed.add_field(name="Cliente", value=client_name[:256], inline=True)

    if skills:
        embed.add_field(name="Habilidades", value=skills[:1024], inline=False)

    footer_text = f"99freelas • {query_label}" if query_label else "99freelas Job Alerts"
    embed.set_footer(text=footer_text)
    embed.timestamp = posted_dt if posted_dt else discord.utils.utcnow()

    content = "🔄 **[UPDATED]** This 99freelas job was updated!" if is_updated else ""
    return content, embed


def format_99freelas_thread_details(job: dict) -> str:
    """
    Builds a detailed Markdown message for the job's discussion thread.
    """
    title = job.get("title", "Untitled Job")
    job_url = job.get("url", "https://www.99freelas.com.br")
    description = job.get("description", "No description provided.")
    budget = job.get("budget", "A combinar / Por proposta")
    skills = job.get("skills", "None specified")
    experience_level = job.get("experience_level", "Não especificado")
    proposals_count = job.get("proposals_count", "0")
    client_name = job.get("client_name", "Anônimo")
    epoch_sec = job.get("epoch_sec", 0)

    if epoch_sec and epoch_sec > 0:
        time_info = f"<t:{epoch_sec}:F> (<t:{epoch_sec}:R>)"
    else:
        time_info = job.get("posted_time", "Recent")

    lines = [
        f"## 🇧🇷 [{title}]({job_url})",
        "",
        f"**💰 Budget / Orçamento:** {budget}",
        f"**📊 Experience Level:** {experience_level}",
        f"**📥 Proposals Sent:** {proposals_count}",
        f"**👤 Client:** {client_name}",
        f"**🕒 Posted:** {time_info}",
        f"**🛠️ Skills:** {skills}",
    ]

    if job.get("is_translated"):
        orig_lang = job.get("original_language", "Portuguese")
        lines.append(f"**🌐 Language:** Translated from **{orig_lang}** to English")

    lines.extend([
        "",
        "### 📝 Full Project Description (English)",
        description,
    ])

    if job.get("is_translated") and job.get("original_description"):
        orig_desc = job.get("original_description", "")[:1000]
        lines.extend([
            "",
            "---",
            f"**Original Text ({job.get('original_language', 'Original')}):**",
            f"> {orig_desc.replace(chr(10), chr(10) + '> ')}",
        ])

    lines.extend([
        "",
        "---",
        f"🔗 **[View Project & Submit Proposal on 99freelas]({job_url})**",
    ])
    return "\n".join(lines)
