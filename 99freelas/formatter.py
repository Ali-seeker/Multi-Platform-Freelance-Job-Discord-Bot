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
        f"**💰 Orçamento:** {budget}",
        f"**📊 Nível de Experiência:** {experience_level}",
        f"**📥 Propostas Enviadas:** {proposals_count}",
        f"**👤 Cliente:** {client_name}",
        f"**🕒 Publicado:** {time_info}",
        f"**🛠️ Habilidades Solicitadas:** {skills}",
        "",
        "### 📝 Descrição Completa do Projeto",
        description,
        "",
        "---",
        f"🔗 **[Ver Projeto e Enviar Proposta no 99freelas]({job_url})**",
    ]
    return "\n".join(lines)
