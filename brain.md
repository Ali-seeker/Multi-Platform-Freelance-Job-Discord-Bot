# 🧠 Project Brain — Multi-Platform Freelance Job Discord Bot

> **Aliases:** `brain.md` · This is the canonical project-knowledge file.
> **Rule:** Every exploration task MUST begin by reading this file. See `claude.md` (agent instructions).

---

## 1. Concept

A modular, multi-platform **Discord bot** system that monitors freelance marketplaces and work communities (**Upwork**, **Guru**, **Freelancer.com**, **PeoplePerHour**, **Truelancer**, **Facebook Groups**, **99freelas**, and **Meta Threads**) for **new job postings** in real time, de-duplicates jobs via SQLite content hashing, and forwards alerts into **dedicated single channels per platform** (`#upwork`, `#guru`, `#freelancer`, `#peopleperhour`, `#truelancer`, `#facebook`, `#99freelas`, `#threads`) as rich embeds with full job details in auto-created threads.

### Key Tenets
1. **Single Channel Per Platform**: All jobs from a platform (across any tracked search query or keyword) post into a single dedicated channel (`#upwork` for Upwork, `#guru` for Guru, `#freelancer` for Freelancer, `#peopleperhour` for PeoplePerHour, `#truelancer` for Truelancer, `#facebook` for Facebook, `#99freelas` for 99freelas, `#threads` for Threads). Each embed clearly tags the matched keyword.
2. **Dedicated Database Table Per Platform**: Every platform has its own table in `jobs.db` (`upwork_jobs`, `guru_jobs`, `freelancer_jobs`, `peopleperhour_jobs`, `truelancer_jobs`, `facebook_jobs`, `[99freelas_jobs]`, `threads_jobs`) to isolate jobs and prevent collisions.
3. **Independent or Parallel Execution**: Each platform can be run individually (`python main.py --platform <name>`), all together in parallel in one process (`python main.py --all`), or across separate terminals.
4. **Fast Polling Without Selenium Job Verification**: 
   - Upwork: Uses GraphQL scraper + Turnstile session refresh when tokens expire.
   - Guru: Uses fast HTTP scraping (`curl_cffi` + `BeautifulSoup`) requiring 0 tokens, 0 cookies, and 0 Selenium. Automatically paginates `/d/jobs/pg/{page}/` for large batches (`limit > 20`).
   - Freelancer: Uses high-speed public REST API (`/api/projects/0.1/projects/active/`) ordered by `time_submitted` (newest first). 0 tokens, 0 cookies, 0 Selenium.
   - PeoplePerHour: Uses direct SSR React state hydration extraction (`window.PPHReact.initialState`) via `curl_cffi` (chrome124) with keywords mapped to `/freelance-{slug}-jobs?sort=latest`. 0 tokens, 0 cookies, 0 Selenium.
   - Truelancer: Uses direct Next.js SSR structured state extraction (`__NEXT_DATA__`) via `curl_cffi` (chrome124) with queries mapped to `/freelance-jobs?page={page}&q={query}`. 0 tokens, 0 cookies, 0 Selenium.
   - Facebook: Uses cookie-based HTTP poller (`c_user` & `xs`) or IMAP email listener (`imaplib` + `BeautifulSoup`). Automatically resolves canonical permalinks (`/groups/{id}/posts/{post_id}/`) and extracts full post descriptions from Facebook's Relay JSON store into Discord embeds and detail threads. 0 browser overhead.
   - 99freelas: Uses high-speed SSR HTML scraper (`curl_cffi` chrome124 + `bs4`) extracting exact millisecond timestamps (`cp-datetime`), experience level, proposal count, and full description. 0 tokens, 0 cookies, 0 Selenium.
   - Threads: Uses direct public SSR search scraping (`curl_cffi` chrome124) extracting preloaded Relay JSON data (`caption.text`, `user`, `taken_at`). 0 tokens, 0 cookies, 0 Selenium.

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
   │  ├─ upwork / guru / freelancer / pph / truelancer / freelas cmds  → slash commands (/add_tracker, /99freelas_add_tracker, etc.)
   │  └─ upwork / guru / freelancer / pph / truelancer / freelas poll  → Platform Poller cogs
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
   ├─ [GURU POLLER]
   │      - Channel: #guru (auto-created if not found)
   │      - Scraper: HTTP + BeautifulSoup (curl_cffi chrome124)
   │      - DB Table: guru_jobs
   │
   ├─ [FREELANCER POLLER]
   │      - Channel: #freelancer (auto-created if not found)
   │      - Scraper: REST API (curl_cffi chrome124)
   │      - DB Table: freelancer_jobs
   │      - De-duplication: sha256(title | description | budget)
   │      - Format: Freelancer blue embed + detail thread
   │
   ├─ [PEOPLEPERHOUR POLLER]
   │      - Channel: #peopleperhour (auto-created if not found)
   │      - Scraper: SSR React state scraper (curl_cffi chrome124)
   │      - DB Table: peopleperhour_jobs
   │      - De-duplication: sha256(title | description | budget)
   │      - Format: PeoplePerHour orange embed + detail thread
   │
   ├─ [TRUELANCER POLLER]
   │      - Channel: #truelancer (auto-created if not found)
   │      - Scraper: Next.js __NEXT_DATA__ scraper (curl_cffi chrome124)
   │      - DB Table: truelancer_jobs
   │      - De-duplication: sha256(title | description | budget)
   │      - Format: Truelancer sky blue embed + detail thread
   │
   ├─ [FACEBOOK POLLER]
   │      - Channel: #facebook (auto-created if not found)
   │      - Listener: HTTP cookie scraper / IMAP Email Listener
   │      - DB Table: facebook_jobs
   │      - De-duplication: sha256(title | description | post_id)
   │      - Format: Facebook blue embed + detail thread
   │
   ├─ [99FREELAS POLLER]
   │      - Channel: #99freelas (auto-created if not found)
   │      - Scraper: SSR HTML scraper (curl_cffi chrome124 + bs4)
   │      - DB Table: [99freelas_jobs]
   │      - De-duplication: sha256(title | description | budget)
   │      - Format: 99freelas emerald green embed + detail thread
   │
   └─ [THREADS POLLER]
          - Channel: #threads (auto-created if not found)
          - Scraper: Public SSR search scraper (curl_cffi chrome124)
          - DB Table: threads_jobs
          - De-duplication: sha256(title | description | job_id)
          - Format: Threads signature dark embed + detail thread
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
│                                  #   (upwork_jobs, guru_jobs, freelancer_jobs, peopleperhour_jobs, truelancer_jobs, facebook_jobs).
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
├── jobs.db                        # 🗄️ SQLITE DATABASE containing platform tables (upwork_jobs, guru_jobs, freelancer_jobs, peopleperhour_jobs, truelancer_jobs, facebook_jobs).
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
├── freelancer/                    # 🏢 FREELANCER.COM PLATFORM PACKAGE
│   ├── __init__.py                #   Exports FreelancerScraper, FreelancerPoller, setup_freelancer.
│   ├── config.py                  #   Freelancer configs, channel settings, tracker mutator helpers.
│   ├── config.json                #   Freelancer tracked queries & dedicated single channel (#freelancer).
│   ├── scraper.py                 #   Freelancer REST API client (active projects).
│   ├── poller.py                  #   Freelancer polling loop; routes to #freelancer and freelancer_jobs table.
│   ├── formatter.py               #   Freelancer embed and thread detail formatter (Blue branding).
│   └── commands.py                #   Freelancer slash commands (/freelancer_add_tracker, etc.).
│
├── peopleperhour/                 # 🏢 PEOPLEPERHOUR PLATFORM PACKAGE
│   ├── __init__.py                #   Exports PeoplePerHourScraper, PeoplePerHourPoller, setup_peopleperhour.
│   ├── config.py                  #   PeoplePerHour configs, channel settings, tracker mutator helpers.
│   ├── config.json                #   PeoplePerHour tracked queries & dedicated single channel (#peopleperhour).
│   ├── scraper.py                 #   PeoplePerHour SSR React state scraper (curl_cffi chrome124).
│   ├── poller.py                  #   PeoplePerHour polling loop; routes to #peopleperhour and peopleperhour_jobs table.
│   ├── formatter.py               #   PeoplePerHour embed and thread detail formatter (Orange branding).
│   └── commands.py                #   PeoplePerHour slash commands (/pph_add_tracker, etc.).
│
├── truelancer/                    # 🏢 TRUELANCER PLATFORM PACKAGE
│   ├── __init__.py                #   Exports TruelancerScraper, TruelancerPoller, setup_truelancer.
│   ├── config.py                  #   Truelancer configs, channel settings, tracker mutator helpers.
│   ├── config.json                #   Truelancer tracked queries & dedicated single channel (#truelancer).
│   ├── scraper.py                 #   Truelancer Next.js __NEXT_DATA__ scraper (curl_cffi chrome124).
│   ├── poller.py                  #   Truelancer polling loop; routes to #truelancer and truelancer_jobs table.
│   ├── formatter.py               #   Truelancer embed and thread detail formatter (Sky Blue branding).
│   └── commands.py                #   Truelancer slash commands (/truelancer_add_tracker, etc.).
│
├── facebook/                      # 🏢 FACEBOOK PLATFORM PACKAGE
│   ├── __init__.py                #   Exports FacebookNotificationScraper, FacebookPoller, setup_facebook.
│   ├── config.py                  #   Facebook configs, channel settings, tracker mutator helpers.
│   ├── config.json                #   Facebook tracked queries & dedicated single channel (#facebook).
│   ├── scraper.py                 #   Direct HTTP notification scraper (curl_cffi chrome124 with c_user & xs).
│   ├── email_listener.py          #   IMAP email notification listener & parser (imaplib + BeautifulSoup).
│   ├── poller.py                  #   Facebook polling loop; routes to #facebook and facebook_jobs table.
│   ├── formatter.py               #   Facebook embed and thread detail formatter (Facebook Blue branding).
│   └── commands.py                #   Facebook slash commands (/facebook_add_tracker, /facebook_status).
│
├── 99freelas/                     # 🏢 99FREELAS PLATFORM PACKAGE
│   ├── __init__.py                #   Exports Freelance99Scraper, Freelance99Poller, setup_99freelas.
│   ├── config.py                  #   99freelas configs, channel settings, tracker mutator helpers.
│   ├── config.json                #   99freelas tracked queries & dedicated single channel (#99freelas).
│   ├── scraper.py                 #   99freelas SSR HTML scraper (curl_cffi chrome124 + BeautifulSoup).
│   ├── poller.py                  #   99freelas polling loop; routes to #99freelas and [99freelas_jobs] table.
│   ├── formatter.py               #   99freelas embed and thread detail formatter (Emerald Green branding).
│   └── commands.py                #   99freelas slash commands (/99freelas_add_tracker, etc.).
│
└── threads/                       # 🏢 THREADS PLATFORM PACKAGE
    ├── __init__.py                #   Exports ThreadsScraper, ThreadsPoller, setup_threads.
    ├── config.py                  #   Threads configs, channel settings, tracker mutator helpers.
    ├── config.json                #   Threads tracked queries & dedicated single channel (#threads).
    ├── scraper.py                 #   Threads public SSR search scraper (curl_cffi chrome124 + Relay JSON parser).
    ├── poller.py                  #   Threads polling loop; routes to #threads and threads_jobs table.
    ├── formatter.py               #   Threads embed and thread detail formatter (Signature Dark branding).
    └── commands.py                #   Threads slash commands (/threads_add_tracker, etc.).
```

---

## 4. Platform Data Contracts & Conventions

### Single Channel Model
Each platform routes all search queries into its single dedicated channel:
- Upwork: `#upwork`
- Guru: `#guru`
- Freelancer: `#freelancer`
- PeoplePerHour: `#peopleperhour`
- Truelancer: `#truelancer`
- Facebook: `#facebook`
- 99freelas: `#99freelas`
- Threads: `#threads`
When a poller starts, `get_or_create_platform_channel()` checks if the channel exists. If not, it creates it automatically in the Discord guild.

### Database Schema (`[{platform}_jobs]`)
```sql
CREATE TABLE IF NOT EXISTS [{platform}_jobs] (
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

3. **Run Freelancer Only**:
   ```powershell
   python main.py --platform freelancer
   ```

4. **Run PeoplePerHour Only**:
   ```powershell
   python main.py --platform peopleperhour
   ```

5. **Run Truelancer Only**:
   ```powershell
   python main.py --platform truelancer
   ```

6. **Run Facebook Only**:
   ```powershell
   python main.py --platform facebook
   ```

7. **Run 99freelas Only**:
   ```powershell
   python main.py --platform 99freelas
   ```

8. **Run Threads Only**:
   ```powershell
   python main.py --platform threads
   ```

9. **Run All Platforms in One Process**:
   ```powershell
   python main.py --all
   ```

10. **Run in Separate Terminals**:
   - Terminal 1: `python main.py --platform upwork`
   - Terminal 2: `python main.py --platform guru`
   - Terminal 3: `python main.py --platform freelancer`
   - Terminal 4: `python main.py --platform peopleperhour`
   - Terminal 5: `python main.py --platform truelancer`
   - Terminal 6: `python main.py --platform facebook`
   - Terminal 7: `python main.py --platform 99freelas`
   - Terminal 8: `python main.py --platform threads`

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

---

## 7. Scaling to 30+ Platforms Strategy

> Full detailed blueprint in `SCALING_STRATEGY.md`.

- **Polling Cadence:** Scale from fast 15–30s polling to **10–15 minute batches (`fetch_interval`: 600–900s)** with 20 jobs per page.
- **Poll Staggering / Jitter:** Stagger platform startup by 15–20 seconds to prevent the thundering herd effect (~2–3 requests/min across the whole system).
- **System Requirements:** A standard **2 vCPU, 4 GB RAM VPS ($5–$8/mo on Ubuntu 22.04 LTS)** easily handles 30+ platforms 24/7.
- **Database Concurrency:** SQLite in WAL mode (`PRAGMA journal_mode=WAL;` and `timeout=30.0`) provides non-blocking concurrent reads and writes.
- **Browser Mutex:** Use a global lock for Chromium session refresh so at most one browser runs at any given second.
- **Process Management:** Run grouped platform clusters via PM2 or Docker Compose for crash isolation and auto-restart.