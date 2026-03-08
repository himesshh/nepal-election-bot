# 🇳🇵 Nepal Election Bot v2 — Setup Guide

## Sources monitored (ranked by trust/speed)
| # | Source | Type | Why |
|---|--------|------|-----|
| 1 | **Onlinekhabar** | Nepali portal | #1 most trusted, fastest updates |
| 2 | **Ekantipur** | Kantipur Media | Most credible traditional media group |
| 3 | **Setopati** | Nepali portal | Best ground reports, counting center updates |
| 4 | **Himalayan Times** | English daily | Best English coverage, high credibility |
| 5 | **Ratopati** | Nepali portal | Fast political breaking news |

All use **free RSS feeds** — no API keys, no paid accounts needed.

---

## Step 1 — Create Discord Bot

1. Go to https://discord.com/developers/applications
2. **New Application** → give it a name like `Nepal Election 2082`
3. Go to **Bot** tab → **Add Bot** → confirm
4. Click **Reset Token** → **copy the token** (keep it secret!)
5. Scroll down → enable **Message Content Intent**
6. Go to **OAuth2 → URL Generator**
   - Check `bot` under Scopes
   - Check these permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`
7. Copy the URL at the bottom → open it in browser → add to your server

## Step 2 — Get Channel ID

1. Discord → **User Settings → Advanced → Developer Mode ON**
2. Right-click the channel you want updates in → **Copy Channel ID**

## Step 3 — Install & Run

```bash
# Install Python 3.10+ first from python.org

# Install dependencies
pip install -r requirements.txt

# Set your credentials
export DISCORD_TOKEN="paste_your_token_here"
export CHANNEL_ID="paste_your_channel_id_here"
export CHECK_INTERVAL="5"   # check every 5 minutes

# Run!
python bot.py
```

**Windows (PowerShell):**
```powershell
$env:DISCORD_TOKEN = "paste_your_token_here"
$env:CHANNEL_ID    = "paste_your_channel_id_here"
python bot.py
```

---

## Bot Commands

| Command | Who | Description |
|---------|-----|-------------|
| `!status` | Everyone | Bot health, sources, articles tracked |
| `!sources` | Everyone | List all monitored sites |
| `!check` | Admin | Force an immediate news check |
| `!addkeyword <word>` | Admin | Add a new keyword to filter |

---

## Run 24/7 for Free

### Option A: Railway.app (recommended, easiest)
1. Create account at https://railway.app
2. New Project → Deploy from GitHub (upload your files to a repo first)
3. Add environment variables in the Railway dashboard:
   - `DISCORD_TOKEN` → your token
   - `CHANNEL_ID` → your channel ID
   - `CHECK_INTERVAL` → 5
4. It runs forever, free tier available

### Option B: Replit
1. Create account at https://replit.com
2. Create a new Python repl → upload `bot.py` and `requirements.txt`
3. Go to **Secrets** (lock icon) → add `DISCORD_TOKEN` and `CHANNEL_ID`
4. Click Run — use https://uptimerobot.com to ping it and keep it alive 24/7

### Option C: Your own PC/server (screen)
```bash
# Install screen
sudo apt install screen

# Run bot in background
screen -S nepalbot
python bot.py
# Press Ctrl+A then D to detach — bot keeps running
```

---

## Customization

### Add/remove sources
Edit the `SOURCES` dict in `bot.py`. Each source needs:
- `rss` — the RSS feed URL
- `base` — homepage URL
- `emoji`, `color`, `priority`

### Add keywords
Use the `!addkeyword` Discord command, or edit `KEYWORDS` in `bot.py`.

### Change check frequency
Set `CHECK_INTERVAL` env variable (in minutes). Minimum recommended: 3.

---

*🗳️ Built for Nepal Election 2082 coverage*
