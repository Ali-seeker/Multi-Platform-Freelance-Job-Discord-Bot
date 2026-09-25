# Multi-Platform Freelance Job Discord Bot

An intelligent, modular, and fully automated Discord bot system that monitors freelance marketplaces (**Upwork**, **Guru**, and **Freelancer.com**) in real-time, de-duplicates job postings via SQLite content hashing, and forwards alerts into **dedicated single channels per platform** (`#upwork`, `#guru`, `#freelancer`) with rich embeds and detailed auto-created discussion threads.

---

## 🌟 Key Features

- **Multi-Platform Architecture:** Modular design where each platform is an isolated package (`upwork/`, `guru/`, `freelancer/`) with its own scraper, poller, formatter, and configuration.
- **Dedicated Single Channels:** All jobs for a platform (across any tracked search query or keyword) are sent to a single dedicated channel (`#upwork`, `#guru`, `#freelancer`). The channel is automatically created in your Discord server if it does not already exist.
- **Isolated SQLite Storage:** Jobs are stored in platform-specific tables (`upwork_jobs`, `guru_jobs`, `freelancer_jobs`) in `jobs.db` using SHA-256 content hashes (`title|description|budget`) to prevent duplicate alerts.
- **Fast, Lightweight Polling:**
  - **Upwork:** GraphQL search API with automatic headless Selenium visitor token refresh when expired (401/403). Private job checking with Selenium has been removed for blazing-fast cycles.
  - **Guru:** Fast public HTTP scraping (`curl_cffi` + `BeautifulSoup`) requiring zero tokens, zero cookies, and zero Selenium. Supports multi-page pagination when `jobs_per_page > 20`.
  - **Freelancer.com:** High-speed REST API client querying active projects ordered by `time_submitted` (newest first). Zero tokens, zero cookies, zero Selenium.
- **Flexible Execution Modes:** Run a single platform, run all platforms together in a single process, or run platforms concurrently in separate terminals.
- **Interactive Discussion Threads:** Creates a thread under each posted job with full client statistics, budget information, full description, and direct apply links.

---

## 🏗️ Directory Structure

```
├── main.py                        # 🚀 Multi-platform CLI runner
├── discord_bot.py                 # 🔄 Backward-compatible entry point
├── db.py                          # 🗄️ Multi-platform SQLite database (upwork_jobs, guru_jobs, freelancer_jobs)
├── logger.py                      # 📝 Global logging setup
├── monitor.py                     # 📊 Status dashboard (:5000/status) with port collision fallback
├── requirements.txt               # 📦 Project dependencies
├── brain.md                       # 🧠 System architecture documentation
├── claude.md                      # 🤖 Agent rulebook & new platform addition blueprint
├── jobs.db                        # 🗄️ SQLite database containing platform tables
│
├── utils/                         # 🧰 Shared cross-platform utilities
│   ├── discord_helpers.py         #   Retry logic, message chunking, timestamp parsing, channel creation
│   └── formatter.py               #   Backward-compatible formatter shim
│
├── upwork/                        # 🏢 Upwork platform package
│   ├── config.json                #   Upwork tracked queries & channel settings
│   ├── config.py                  #   Upwork configuration loader
│   ├── scraper.py                 #   GraphQL scraper
│   ├── auth_manager.py            #   Cloudflare Turnstile bypass & visitor auth
│   ├── poller.py                  #   Upwork polling loop (posts to #upwork)
│   ├── formatter.py               #   Upwork rich embed and thread formatter
│   └── commands.py                #   Upwork slash commands (/add_tracker, /list_trackers)
│
├── guru/                          # 🏢 Guru platform package
│   ├── config.json                #   Guru tracked queries & channel settings
│   ├── config.py                  #   Guru configuration loader
│   ├── scraper.py                 #   Guru HTTP scraper (curl_cffi + BeautifulSoup)
│   ├── poller.py                  #   Guru polling loop (posts to #guru)
│   ├── formatter.py               #   Guru rich embed (Cyan) and thread formatter
│   └── commands.py                #   Guru slash commands (/guru_add_tracker, /guru_list_trackers)
│
└── freelancer/                    # 🏢 Freelancer.com platform package
    ├── config.json                #   Freelancer tracked queries & channel settings
    ├── config.py                  #   Freelancer configuration loader
    ├── scraper.py                 #   Freelancer REST API client (active projects)
    ├── poller.py                  #   Freelancer polling loop (posts to #freelancer)
    ├── formatter.py               #   Freelancer rich embed (Blue) and thread formatter
    └── commands.py                #   Freelancer slash commands (/freelancer_add_tracker, etc.)
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.9+
- Google Chrome installed (for Upwork's visitor token refresh)
- Discord Bot Token with Message Content Intent enabled

### 2. Installation
```powershell
git clone <repo-url>
cd Upwork-Discord-Bot
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```env
DISCORD_TOKEN=your_discord_bot_token_here
```
*(Upwork visitor authentication tokens are automatically extracted and refreshed by the bot; no manual cookie or token copying is required).*

---

## 💻 Running the Bot

### Option 1: Run Upwork Only
```powershell
python main.py --platform upwork
```

### Option 2: Run Guru Only
```powershell
python main.py --platform guru
```

### Option 3: Run Freelancer Only
```powershell
python main.py --platform freelancer
```

### Option 4: Run All Platforms in One Process
```powershell
python main.py --all
```

### Option 5: Run in Separate Terminals (Parallel)
- **Terminal 1:** `python main.py --platform upwork`
- **Terminal 2:** `python main.py --platform guru`
- **Terminal 3:** `python main.py --platform freelancer`

---

## ⚙️ Configuration

Configure tracked search queries, intervals, and batch sizes in `{platform}/config.json`:

```json
{
    "channel_name": "upwork",
    "channel_id": "",
    "tracked_queries": [
        {
            "query": "automation",
            "url": "https://www.upwork.com/nx/search/jobs/?q=automation&sort=recency",
            "label": "Automation"
        }
    ],
    "fetch_interval": 10,
    "jobs_per_page": 10
}
```
- `fetch_interval`: Delay between polling cycles in seconds.
- `jobs_per_page`: Number of jobs fetched per search query (e.g. 10 or 20).

---

## ⏱️ Real-Time Recency & Exact Timestamps

All platforms poll the freshest, most recently posted jobs first:
- **Upwork:** Search API queries are sorted by `"sort": "recency"`.
- **Guru:** Search results are ordered by `Newest` by default.
- **Freelancer.com:** REST API queries are ordered by `sort_field=time_submitted` (newest first).

When jobs are sent to Discord:
1. **Dynamic Discord Timestamps:** Parsed timestamps are rendered using Discord markdown `<t:UNIX:f>` (exact date & time) and `<t:UNIX:R>` (dynamic relative time like `5 minutes ago`), automatically localized to the viewer's device timezone.
2. **Official Embed Timestamp:** `embed.timestamp` is set directly to the job's published time, rendering in the Discord embed footer.
3. **Exact Thread Timestamps:** Job discussion threads display the exact posted time and relative age.

---

## 📋 Clear Step-by-Step Terminal Logs

Every polling cycle outputs numbered, platform-tagged log lines in the terminal:

```
[UPWORK] [Step 1/5] 🔍 Scanning query: 'Automation' (Batch limit: 20 jobs)...
[UPWORK] [Step 2/5] 🌐 Received 20 jobs from Upwork GraphQL API
[UPWORK] [Step 3/5] 🗄️ Checking 20 jobs against 'upwork_jobs' table...
[UPWORK] [Step 4/5] 💾 ✨ [NEW] Saved to 'upwork_jobs': 21031845... | RAG Chatbot Developer
[UPWORK] [Step 5/5] 💬 Sent to #upwork with details thread
[UPWORK] ✅ Cycle complete for 'Automation': 1 new jobs posted to #upwork.

[GURU] [Step 1/5] 🔍 Scanning query: 'Automation' (Batch limit: 20 jobs)...
[GURU] [Step 2/5] 🌐 Scraped 20 jobs from Guru search
[GURU] [Step 3/5] 🗄️ Checking 20 jobs against 'guru_jobs' table...
[GURU] ⏭️ Cycle complete for 'Automation': No new unposted jobs.

[FREELANCER] [Step 1/5] 🔍 Scanning query: 'Automation' (Batch limit: 20 jobs)...
[FREELANCER] [Step 2/5] 🌐 Received 20 jobs from Freelancer REST API
[FREELANCER] [Step 3/5] 🗄️ Checking 20 jobs against 'freelancer_jobs' table...
[FREELANCER] [Step 4/5] 💾 ✨ [NEW] Saved to 'freelancer_jobs': 40732644 | Comprehensive AI...
[FREELANCER] [Step 5/5] 💬 Sent to #freelancer with details thread
[FREELANCER] ✅ Cycle complete for 'Automation': 1 new jobs posted to #freelancer.
```
