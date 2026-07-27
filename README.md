# Upwork Discord Bot

An intelligent and fully automated Discord bot that scrapes new freelance jobs from Upwork in real-time and forwards them to specific Discord channels with rich, formatted embeds.

## Features
- **Real-Time Job Polling:** Uses Upwork's GraphQL API to fetch the latest job postings.
- **Cloudflare Bypass Mechanism:** Automatically refreshes session tokens (cookies and Bearer tokens) using headless Selenium when Cloudflare blocks the API (401/403).
- **Private Job Filtering:** Uses Selenium to navigate directly to job URLs to detect and filter out "Private/Invite-only" jobs before posting them to Discord.
- **Duplicate Prevention (SQLite):** Tracks jobs by generating a unique hash (`title` + `description` + `budget`). It automatically identifies and tags jobs that are entirely new (`[NEW]`) or edited by the client (`[UPDATED]`).
- **Dynamic Search Configuration:** Supports both raw keywords (e.g., `Python`) and Upwork search URLs in the configuration.
- **Discord Integration:** Uses `discord.py` to send beautiful embeds and optionally creates threads in Forum channels. Includes slash commands (e.g., `/add`) to easily register new search trackers.

## Architecture & Core Files
- `discord_bot.py`: The main entry point. Initializes the bot, connects to Discord, and starts the poller.
- `scraper.py`: Manages the direct GraphQL queries to Upwork's search API.
- `cogs/poller.py`: The background engine that loops through tracked queries, orchestrates scraping, compares against the database, and pushes to Discord.
- `auth_manager.py`: Handles Cloudflare bypassing by spawning a headless browser on the Upwork homepage to extract fresh authentication headers.
- `job_verifier.py`: Fallback Selenium verifier to confirm if a specific job link is public or private.
- `db.py`: SQLite database manager for tracking previously posted jobs.
- `utils/formatter.py`: Generates the rich Discord embeds and UI presentation.

## Prerequisites
- Python 3.9+
- Chrome/Chromium installed (for Selenium)
- Discord Bot Token

## Setup
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your details:
   ```env
   DISCORD_TOKEN=your_bot_token_here
   ```
4. Run the bot:
   ```bash
   python discord_bot.py
   ```

## Configuration (`config.json`)
You can configure the bot to search for specific terms and route them to designated channels. The `url` field accepts either a raw keyword (e.g., `"React"`) or a full Upwork search URL.
```json
[
    {
        "url": "Python",
        "channel_id": 123456789012345678,
        "label": "Python Jobs"
    }
]
```
