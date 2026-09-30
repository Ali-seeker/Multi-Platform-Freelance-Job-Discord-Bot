# 🚀 30+ Freelance Platform Scaling Strategy

> **Canonical Strategy Document** for scaling the Multi-Platform Freelance Job Discord Bot to **30+ concurrent platforms** operating 24/7.
> Referenced directly in `brain.md` and `claude.md`.

---

## 1. Executive Summary

Scaling from 7 platforms to 30+ platforms requires transitioning from high-frequency aggressive polling (15–30s) to **cadence-based batch polling (10–15 minutes / 600–900s)** with **poll staggering (jitter)** and **lock-free database concurrency**.

With this strategy:
- 30 platforms execute smoothly on a modest **$4–$6/month VPS (2 vCPU, 4 GB RAM)**.
- Total network load is only **~2 to 3 lightweight HTTP requests per minute**.
- Zero platform bot-detection / IP-ban risk due to natural human-like polling intervals.
- High database throughput with zero SQLite lock collisions.

---

## 2. Polling Cadence & Jitter Strategy

### A. Fetch Interval: 10–15 Minutes
In each platform's `config.json`:
- **10 Minutes (Fast Track):** `"fetch_interval": 600`
- **15 Minutes (Standard):** `"fetch_interval": 900`
- **Batch Size:** `"jobs_per_page": 20`

### B. Startup Staggering (Anti-Thundering Herd)
If 30 platforms start at the exact same millisecond, they will simultaneously launch 30 network requests and dozens of Discord API calls.

To prevent this, apply an initial offset delay when each platform cog boots:
```python
# In each platform's poller before the first loop execution:
@poll_platform.before_loop
async def before_poll(self):
    await self.bot.wait_until_ready()
    # Stagger boot across platforms by 15-20 seconds:
    offset = PLATFORM_INDEX * 20  # e.g., 0s, 20s, 40s...
    await asyncio.sleep(offset)
```

With 30 platforms staggered over 600–900s:
$$\text{Average requests per minute} = \frac{30 \text{ platforms}}{10 \text{ minutes}} = 3 \text{ requests/min}$$
The bot stays almost completely idle, consuming less than 5% CPU.

---

## 3. Hardware & System Requirements

### Workload Profile
- **Headless HTTP Platforms (~25–28 platforms):** Use `curl_cffi` (Chrome 124 TLS impersonation) + `BeautifulSoup`. Each platform consumes only ~15–25 MB RAM and negligible CPU.
- **Headless Browser Platforms (~2–3 platforms like Upwork):** Use Selenium / Chromium only for temporary session/token refresh (lasts hours or days). Spikes RAM by ~300–400 MB for 20–30 seconds during auth refresh.

### Server Sizing Matrix

| Metric | Minimum (Testing) | Recommended (Production 24/7) | High-Cap (50+ Platforms) |
| :--- | :--- | :--- | :--- |
| **CPU** | 1 vCPU | **2 vCPUs** | 4 vCPUs |
| **RAM** | 2 GB | **4 GB** | 8 GB |
| **Storage** | 15 GB SSD | **25 GB SSD** | 40 GB NVMe |
| **OS** | Windows 10/11 / Ubuntu 22.04 | **Ubuntu 22.04 / 24.04 LTS** | Ubuntu 24.04 LTS / Debian 12 |
| **Est. Cost** | ~$4/mo (Hetzner / Lightsail) | **~$5–$8/mo (Hetzner / Contabo / DO)** | ~$12–$16/mo |

---

## 4. Database Scaling: Lock-Free SQLite (WAL Mode)

When 30 platforms write to `jobs.db` asynchronously, standard SQLite can occasionally raise:
`sqlite3.OperationalError: database is locked`.

### Solution: Enable WAL (Write-Ahead Logging) & Busy Timeout
In `db.py`:
```python
def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)  # 30-second busy timeout
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")        # Concurrent reads while writing
    conn.execute("PRAGMA synchronous=NORMAL;")      # Fast writes without disk stalls
    return conn
```
- **WAL Mode Benefits:** Readers never block writers, and writers never block readers.
- **Dedicated Tables:** Each platform writes strictly to `{platform}_jobs`, ensuring queries are indexed and fast.

---

## 5. Browser Resource Management: Global Mutex Lock

For platforms that require headless Chrome (e.g. Upwork's Cloudflare Turnstile token refresh):
- **Never launch multiple Chromium instances simultaneously.**
- Use a global `asyncio.Lock()` in `utils/browser_lock.py`:
```python
import asyncio

BROWSER_LOCK = asyncio.Lock()

async def acquire_browser_session():
    async with BROWSER_LOCK:
        # Launch headless chrome, refresh token, close chrome
        yield
```
This guarantees system RAM never spikes above ~1.5 GB total even with 30 platforms running.

---

## 6. Execution Architectures for 30 Platforms

### Option A: Clustered Process Runner (Recommended for Simplicity)
Group platforms into 5 clusters (6 platforms each):
- `Cluster 1 (Top Tier):` Upwork, Guru, Freelancer, PeoplePerHour, Truelancer, 99freelas
- `Cluster 2 (Tech/Dev):` Platforms 7–12
- `Cluster 3 (Content/Design):` Platforms 13–18
- `Cluster 4 (General/Micro):` Platforms 19–24
- `Cluster 5 (Regional/Special):` Platforms 25–30

Run each cluster in a separate background terminal or PM2 process:
```powershell
python main.py --cluster 1
python main.py --cluster 2
...
```

### Option B: PM2 Process Manager (Recommended for Linux VPS 24/7)
Install PM2 (`npm install -g pm2`):
`ecosystem.config.js`:
```javascript
module.exports = {
  apps: [
    {
      name: "bot-cluster-1",
      script: "main.py",
      args: "--platform upwork,guru,freelancer,peopleperhour,truelancer,facebook",
      interpreter: "python3",
      autorestart: true,
      max_memory_restart: "1G"
    },
    // Add additional clusters...
  ]
};
```
Commands:
```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

---

## 7. Discord Rate Limit Safety

- **Discord Gateway Limit:** 1 bot token allows up to 50 requests/second globally.
- **Channel Limit:** 5 messages per 5 seconds per individual channel.
- **Single Channel Model:** Because every platform has its **own dedicated channel** (`#upwork`, `#guru`, `#facebook`, etc.), messages to different channels never share channel rate limit buckets.
- **Retry Mechanism:** All Discord calls route through `utils.discord_helpers.send_with_retry()`, which automatically sleeps on HTTP 429 backoff headers.

---

## 8. Summary Checklist for Adding New Platforms (Up to 30)

- [ ] Set `"fetch_interval": 600` or `900` (10–15 min) in `{platform}/config.json`.
- [ ] Add offset sleep in poller initialization to stagger execution.
- [ ] Ensure SQLite WAL mode is active in `db.py`.
- [ ] Implement headless HTTP scraping (`curl_cffi` Chrome 124) wherever possible (0 browser overhead).
- [ ] Route all jobs to a single dedicated channel `#{platform}` with an auto-created detail thread.
