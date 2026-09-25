# 🤖 Agent Instructions — Multi-Platform Freelance Job Discord Bot

> This file is the **rulebook for AI Agents** working on this repository.
> **READ THIS FILE FIRST before every single task.** Then follow the rules below.

---

## 1. Mandatory Reading Order

Before touching *any* code, config, or answer:

1. ⬅️ **READ `brain.md`** — the canonical project-knowledge file (architecture, multi-platform flows, directory structure, data contracts, and gotchas).
2. ⬅️ **READ `claude.md`** (this file) — the agent rulebook and platform addition blueprint.
3. Only then explore the actual source files for the task at hand.

> **🔍 EXPLORATION RULE:** For **every exploration task**, the agent MUST ground itself with
> **`brain.md`** as the starting map. Do not re-derive project structure from scratch;
> `brain.md` is the single source of truth for architecture.

> **📐 CONSISTENCY RULE:** If you find *any* mismatch between `brain.md` and the actual code,
> trust the **code**, fix `brain.md`, and note it in your task summary.

---

## 2. Project in One Line

A modular, multi-platform Discord bot system that polls freelancing platforms (Upwork, Guru, PeoplePerHour, etc.) for new jobs, de-duplicates and tracks updates via dedicated SQLite tables per platform, and posts rich embeds + detail threads to single dedicated channels (`#upwork`, `#guru`, etc.).

---

## 3. Architecture & File Structure Rule

The codebase is split into **Global Files** (in root & `utils/`) and **Platform-Specific Packages** (inside `{platform}/` folders):

```
E:\Upwork-Discord-Bot\
│
├── main.py                        # 🚀 Multi-platform CLI runner (--platform upwork / --platform all)
├── discord_bot.py                 # 🔄 Backward-compatible entry point
├── db.py                          # 🗄️ Global SQLite database layer (per-platform tables: upwork_jobs, guru_jobs)
├── logger.py                      # 📝 Global logging setup
├── monitor.py                     # 📊 Global Flask status dashboard (:5000/status) with port collision fallback
├── .env                           # 🔒 Global environment secrets (DISCORD_TOKEN, platform tokens)
├── .env.example                   # 📄 Environment template
├── requirements.txt               # 📦 Global dependencies
├── brain.md                       # 🧠 Canonical project knowledge
├── claude.md                      # 🤖 Agent rulebook & platform guide (this file)
├── jobs.db                        # 🗄️ SQLite database containing platform tables
│
├── utils/                         # 🧰 Global shared utilities
│   ├── __init__.py
│   └── discord_helpers.py         #   Shared Discord utilities (send_with_retry, split_message, get_or_create_platform_channel)
│
└── upwork/                        # 🏢 Upwork platform package
    ├── __init__.py                #   Package init & setup helper
    ├── config.py                  #   Upwork configs, queries, headers, env vars
    ├── config.json                #   Upwork tracked queries & single channel config (#upwork)
    ├── scraper.py                 #   Upwork GraphQL scraper & parser
    ├── auth_manager.py            #   Upwork Cloudflare bypass & Selenium session refresh
    ├── poller.py                  #   Upwork polling loop (posts to #upwork, saves to upwork_jobs)
    ├── formatter.py               #   Upwork embed and detail thread formatter
    └── commands.py                #   Upwork slash commands (/add_tracker, /delete_tracker, /list_trackers)
```

### Core Architecture Rules:
1. **Global files live in root or `utils/`**: Anything that serves all platforms (logging, database engine, Flask dashboard, Discord retry helpers, runner CLI) remains at root.
2. **Platform-specific files live inside `{platform}/`**: Every platform has its own folder containing its config, scraper, poller, formatter, and slash commands.
3. **Single Channel Per Platform**: All jobs from any given platform (regardless of keyword/query) are sent to a single dedicated channel named after that platform (e.g. `#upwork`, `#guru`, `#peopleperhour`). The matched keyword is tagged in the job embed.
4. **Dedicated DB Table Per Platform**: Every platform has its own table in `jobs.db` (`{platform}_jobs`), preventing cross-platform collision.
5. **No Selenium Private Job Verification**: Upwork private job inspection via Selenium has been removed. Listings are processed and de-duplicated directly via content hashing (`sha256` of `title|description|budget`).

---

## 4. Blueprint: How to Add a New Freelancing Platform (e.g. Guru, PeoplePerHour)

When it is time to add another freelancing platform, follow this exact step-by-step checklist:

### Step 1: Create Platform Directory
Create a new folder in the root named after the platform: `{platform}/` (e.g. `guru/` or `peopleperhour/`).

### Step 2: Create `{platform}/config.json`
Configure the dedicated channel name and tracked search queries:
```json
{
    "channel_name": "guru",
    "channel_id": "",
    "tracked_queries": [
        { "query": "Python", "label": "Python" },
        { "query": "React", "label": "React" }
    ],
    "fetch_interval": 30
}
```

### Step 3: Create `{platform}/config.py`
Load environment variables from root `.env` (e.g. `GURU_API_KEY` or credentials), read `{platform}/config.json`, and define tracker mutation functions (`add_new_tracker`, `remove_tracker_by_label`, `set_channel_id`).

### Step 4: Create `{platform}/scraper.py`
Implement the platform's HTTP client or scraper:
- Method `fetch_jobs(query: str) -> list[dict]`
- Ensure `parse_job(raw)` normalizes data into standard dictionary keys:
  `job_id, title, description, budget, skills, posted_time` (plus platform specifics like url).

### Step 5: Create `{platform}/formatter.py`
Build the Discord presentation:
- `format_job_message(job, details, is_updated, query_label) -> (content, discord.Embed)`
- `format_thread_details(details, job) -> str`
- Include the platform brand color and the matched keyword tag.

### Step 6: Create `{platform}/poller.py`
Implement a `commands.Cog` polling loop:
- In `poll_platform()`, resolve/create the single dedicated channel using:
  `channel = await get_or_create_platform_channel(bot, platform_name="{platform}", preferred_channel_id=CHANNEL_ID, save_id_callback=set_channel_id)`
- Compute content hash: `hashlib.sha256(f"{title}|{description}|{budget}".encode("utf-8")).hexdigest()`.
- Check de-duplication: `db.get_job_hash(job_id, query, platform="{platform}")`.
- Save job: `db.save_job(job, query, current_hash, platform="{platform}")`.
- Post to `channel` using `send_with_retry` and create a details thread.

### Step 7: Create `{platform}/commands.py` (Optional)
Implement platform-specific slash commands (e.g. `/{platform}_add_tracker`, `/{platform}_delete_tracker`, `/{platform}_list_trackers`).

### Step 8: Create `{platform}/__init__.py`
Export setup helper:
```python
async def setup_{platform}(bot):
    await bot.add_cog({Platform}Commands(bot))
    await bot.add_cog({Platform}Poller(bot))
```

### Step 9: Register in `main.py`
In `main.py`, add the platform to `AVAILABLE_PLATFORMS`:
```python
AVAILABLE_PLATFORMS["{platform}"] = {
    "name": "{Platform}",
    "setup": lambda bot: _setup_{platform}_platform(bot),
}
```
When `main.py` boots, `db.init_db("{platform}")` automatically creates the `{platform}_jobs` SQLite table.

---

## 5. Execution Modes

You can run platforms in any combination:

1. **Run a single platform**:
   ```powershell
   python main.py --platform upwork
   ```

2. **Run all platforms in parallel in a single process**:
   ```powershell
   python main.py --platform all
   # or
   python main.py --all
   ```

3. **Run platforms in parallel across separate terminals**:
   - Terminal 1: `python main.py --platform upwork`
   - Terminal 2: `python main.py --platform guru`
   - Terminal 3: `python main.py --platform freelancer`
   *(Port conflict on `:5000` is handled automatically by `monitor.py`)*

4. **Backward-compatible execution**:
   ```powershell
   python discord_bot.py
   ```

---

## 6. Verification Commands

```powershell
# Compile-check all Python files
python -m py_compile main.py discord_bot.py db.py logger.py monitor.py utils/discord_helpers.py upwork/config.py upwork/scraper.py upwork/auth_manager.py upwork/formatter.py upwork/poller.py upwork/commands.py guru/config.py guru/scraper.py guru/formatter.py guru/poller.py guru/commands.py freelancer/config.py freelancer/scraper.py freelancer/formatter.py freelancer/poller.py freelancer/commands.py freelancer/__init__.py

# CLI help validation
python main.py --help

# Test database tables and migration
python -c "import db; print(db.get_all_job_counts())"
```

---

## 7. Git & Documentation Workflow (Mandatory Before Every Push)

Before running `git push` to GitHub:
1. 📝 **Update `README.md`**: Document any new platform capabilities, configuration options, timestamp formats, or CLI flags.
2. 🧠 **Update `brain.md`**: Keep canonical architecture and component status synchronized.
3. 🤖 **Update `claude.md`**: Ensure platform checklists and blueprints match current patterns.
4. 🧪 **Validate Python Code**: Run `python -m py_compile` across all files to ensure no syntax errors.
5. 🚀 **Commit & Push**: Stage changed files, create clean descriptive commits, and push to GitHub (`git push origin main`).

---

## 8. Final Checklist Before You Finish

- [ ] Read `claude.md` + `brain.md` before making edits
- [ ] No secrets exposed, logged, or committed in `.env`
- [ ] Platform code isolated in its `{platform}/` directory
- [ ] Each platform uses its dedicated single channel (`#{platform}`) and DB table (`{platform}_jobs`)
- [ ] Terminal logs clearly specify every step and prefix with `[{PLATFORM}]`
- [ ] `brain.md` and `claude.md` updated and kept in root
- [ ] **Always update `README.md` before pushing to GitHub**
- [ ] `python -m py_compile` passes cleanly
- [ ] Push verified changes to GitHub (`git push`)