# 🧠 Project Brain — Multi-Platform Freelance Job Discord Bot

> **Aliases:** `brain.md` · This is the canonical project-knowledge file.
> **Rule:** Every exploration task MUST begin by reading this file. See `claude.md` (agent instructions).

---

## 1. Concept

A modular, multi-platform **Discord bot** system that monitors freelance marketplaces (**Upwork**, **Guru**, and planned platforms such as **PeoplePerHour**, **Freelancer**, etc.) for **new job postings** in real time, de-duplicates jobs via SQLite content hashing, and forwards alerts into **dedicated single channels per platform** (`#upwork`, `#guru`, etc.) as rich embeds with full job details in auto-created threads.

### Key Tenets
1. **Single Channel Per Platform**: All jobs from a platform (across any tracked search query or keyword) post into a single dedicated channel (`#upwork` for Upwork, `#guru` for Guru). Each embed clearly tags the matched keyword.
2. **Dedicated Database Table Per Platform**: Every platform has its own table in `jobs.db` (`upwork_jobs`, `guru_jobs`, etc.) to isolate jobs and prevent collisions.
3. **Independent or Parallel Execution**: Each platform can be run individually (`python main.py --platform upwork` or `python main.py --platform guru`), all together in parallel in one process (`python main.py --all`), or across separate terminals.
4. **Fast Polling Without Selenium Job Verification**: 
   - Upwork: Uses GraphQL scraper + Turnstile session refresh when tokens expire.
   - Guru: Uses fast HTTP scraping (`curl_cffi` + `BeautifulSoup`) requiring 0 tokens, 0 cookies, and 0 Selenium. Automatically paginates `/d/jobs/pg/{page}/` for large batches (`limit > 20`).

---

## 2. High-Level Flow (End-to-End)

```
main.py (CLI entry point)  [--platform <name> / --all]
   │
   ├─ db.init_db(platform)                → ensures {platform}_jobs table exists in jobs.db
   │                                        (auto-migrates legacy 'jobs' table to 'upwork_jobs')
   ├─ create_bot()                        → discord.py commands.Bot
   │
   ▼
 bot.setup_hook()
   │  loads platform cogs:
   │  ├─ upwork / guru commands           → slash commands (/add_tracker, /guru_add_tracker, /sync)
   │  └─ upwork / guru poller             → UpworkPoller / GuruPoller cogs
   │
   ▼
 bot.on_ready()
   │  start_dashboard()                   → monitor.py (Flask :5000/status with port fallback)
   │
   ▼
 Platform Pollers (Concurrent background tasks):
   │
   ├─ [UPWORK POLLER]
   │      - Channel: #upwork
   │      - Scraper: GraphQL + curl_cffi (Selenium on auth refresh)
   │      - DB Table: upwork_jobs
   │
   └─ [GURU POLLER]
          - Channel: #guru (auto-created if not found)
          - Scraper: HTTP + BeautifulSoup (curl_cffi chrome124)
          - DB Table: guru_jobs
          - De-duplication: sha256(title | description | budget)
          - Format: Guru cyan/blue embed + detail thread
```

---

## 3. Directory & File Structure

```
E:\Upwork-Discord-Bot\
│
├── main.py                        # 🚀 MULTI-PLATFORM CLI. Runs single platform or all platforms.
│                                  #   Flags: --platform <name> / --all
│
├── discord_bot.py                 # 🔄 BACKWARD-COMPATIBLE ENTRY POINT.
│                                  #   Delegates to main.py (defaults to Upwork).
│
├── db.py                          # 🗄️ MULTI-PLATFORM SQLITE LAYER.
│                                  #   Manages jobs.db with dedicated tables per platform
│                                  #   (upwork_jobs, guru_jobs). Handles migration and cleanup.
│
├── logger.py                      # 📝 GLOBAL LOGGING. Console formatting + rotating file (logs/bot.log).
│
├── monitor.py                     # 📊 GLOBAL STATUS DASHBOARD. Flask app exposing GET /status
│                                  #   with automatic port collision fallback for multi-terminal runs.
│
├── .env                           # 🔒 SECRETS (gitignored). DISCORD_TOKEN + platform tokens.
├── .env.example                   # 📄 TEMPLATE for environment variables.
├── requirements.txt               # 📦 DEPENDENCIES: requests, curl_cffi, discord.py, selenium, bs4.
├── brain.md                       # 🧠 CANONICAL ARCHITECTURE & KNOWLEDGE (this file).
├── claude.md                      # 🤖 AGENT RULEBOOK & NEW PLATFORM ADDITION BLUEPRINT.
├── jobs.db                        # 🗄️ SQLITE DATABASE containing platform tables (upwork_jobs, guru_jobs).
│
├── utils/                         # 🧰 GLOBAL SHARED UTILITIES
│   ├── __init__.py                #   Exports common utilities.
│   ├── discord_helpers.py         #   send_with_retry (429 handling), split_message, format_relative_time,
│   │                              #   get_or_create_platform_channel (single channel management).
│   └── formatter.py               #   Backward-compatible shim re-exporting formatters.
│
├── upwork/                        # 🏢 UPWORK PLATFORM PACKAGE
│   ├── __init__.py                #   Exports UpworkScraper, AuthManager, UpworkPoller, setup_upwork.
│   ├── config.py                  #   Upwork configs, GraphQL queries, headers, mutation helpers.
│   ├── config.json                #   Upwork tracked queries, single channel (#upwork), fetch interval.
│   ├── scraper.py                 #   Upwork GraphQL scraper (curl_cffi impersonate="chrome124").
│   ├── auth_manager.py            #   Headless Selenium Cloudflare Turnstile bypass & visitor auth.
│   ├── poller.py                  #   Upwork polling cog; routes to #upwork and upwork_jobs table.
│   ├── formatter.py               #   Upwork embed and detail thread layout with keyword tag.
│   └── commands.py                #   Upwork slash commands (/add_tracker, /delete_tracker, /list_trackers).
│
├── guru/                          # 🏢 GURU PLATFORM PACKAGE
│   ├── __init__.py                #   Exports GuruScraper, GuruPoller, setup_guru.
│   ├── config.py                  #   Guru configs, channel settings, tracker mutation helpers.
│   ├── config.json                #   Guru tracked queries & dedicated single channel (#guru).
│   ├── scraper.py                 #   Guru HTTP scraper (curl_cffi + BeautifulSoup).
│   ├── poller.py                  #   Guru polling loop; routes to #guru and guru_jobs table.
│   ├── formatter.py               #   Guru embed and thread detail formatter (Cyan branding).
│   └── commands.py                #   Guru slash commands (/guru_add_tracker, /guru_delete_tracker).
│
├── cogs/                          # 🔄 BACKWARD-COMPATIBLE COG SHIMS
│   ├── poller.py                  #   Re-exports from upwork.poller.
│   └── tracker_commands.py        #   Re-exports from upwork.commands.
│
├── config.py                      # 🔄 BACKWARD-COMPATIBLE CONFIG SHIM (re-exports upwork.config).
├── scraper.py                     # 🔄 BACKWARD-COMPATIBLE SCRAPER SHIM (re-exports upwork.scraper).
└── auth_manager.py                # 🔄 BACKWARD-COMPATIBLE AUTH SHIM (re-exports upwork.auth_manager).
```

---

## 4. Platform Data Contracts & Conventions

### Single Channel Model
Each platform routes all search queries into its single dedicated channel:
- Upwork: `#upwork`
- Guru: `#guru`
When a poller starts, `get_or_create_platform_channel()` checks if the channel exists. If not, it creates it automatically in the Discord guild.

### Database Schema (`{platform}_jobs`)
```sql
CREATE TABLE IF NOT EXISTS {platform}_jobs (
    job_id       TEXT,
    url_source   TEXT,
    title        TEXT NOT NULL,
    description  TEXT,
    budget       TEXT,
    skills       TEXT,
    posted_time  TEXT,
    fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT DEFAULT '',
    PRIMARY KEY (job_id, url_source)
);
```

---

## 5. Execution Modes

1. **Run Upwork Only**:
   ```powershell
   python main.py --platform upwork
   ```

2. **Run Guru Only**:
   ```powershell
   python main.py --platform guru
   ```

3. **Run All Platforms (Upwork + Guru)**:
   ```powershell
   python main.py --all
   ```

4. **Run in Separate Terminals**:
   - Terminal 1: `python main.py --platform upwork`
   - Terminal 2: `python main.py --platform guru`

---

## 6. Timestamps & Logging Contracts

### Exact Timestamp Formatting
- All platforms parse raw posted time via `utils.discord_helpers.parse_posted_time(raw_time)`.
- Returns `(dt, exact_discord, relative_discord)` where `exact_discord` is `<t:{epoch}:f>` and `relative_discord` is `<t:{epoch}:R>`.
- `embed.timestamp` is set to `dt` (the actual job post time), showing natively in Discord embed footers.
- Detail threads show `- **Posted Exact:** <t:{epoch}:f> (<t:{epoch}:R>)`.

### Step-by-Step Logging Standard
Every poller loop logs 5 numbered steps prefixed by `[{PLATFORM}]`:
- `[PLATFORM] [Step 1/5] 🔍 Scanning query: '{label}'...`
- `[PLATFORM] [Step 2/5] 🌐 Received {n} jobs from API/Scraper`
- `[PLATFORM] [Step 3/5] 🗄️ Checking {n} jobs against '{platform}_jobs' table...`
- `[PLATFORM] [Step 4/5] 💾 {prefix} Saved to '{platform}_jobs': {id} | {title}`
- `[PLATFORM] [Step 5/5] 💬 Sent to #{channel} with details thread`