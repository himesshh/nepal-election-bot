"""
🇳🇵 Nepal Election 2082 — Discord News Bot v2
Sources: Onlinekhabar, Ekantipur, Setopati, Himalayan Times, Ratopati
+ Election Commission of Nepal official data
Free, no API keys needed — runs 24/7
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import feedparser
import json
import os
import logging
import hashlib
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ─── CONFIG ───────────────────────────────────────────────────────────────────

DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID      = int(os.getenv("CHANNEL_ID", "0"))
CHECK_INTERVAL  = int(os.getenv("CHECK_INTERVAL", "5"))   # minutes
SEEN_FILE       = "seen.json"

# ─── NEWS SOURCES (all free RSS) ──────────────────────────────────────────────

SOURCES = {
    "Onlinekhabar": {
        "rss":      "https://www.onlinekhabar.com/feed",
        "base":     "https://www.onlinekhabar.com",
        "emoji":    "🟠",
        "color":    0xF57C00,
        "priority": 1,   # higher = shown first
    },
    "Ekantipur": {
        "rss":      "https://ekantipur.com/rss",
        "base":     "https://ekantipur.com",
        "emoji":    "🔵",
        "color":    0x1565C0,
        "priority": 2,
    },
    "Setopati": {
        "rss":      "https://www.setopati.com/feed",
        "base":     "https://www.setopati.com",
        "emoji":    "⚪",
        "color":    0x546E7A,
        "priority": 3,
    },
    "Himalayan Times": {
        "rss":      "https://thehimalayantimes.com/feed/",
        "base":     "https://thehimalayantimes.com",
        "emoji":    "🏔️",
        "color":    0x00897B,
        "priority": 4,
    },
    "Ratopati": {
        "rss":      "https://ratopati.com/feed",
        "base":     "https://ratopati.com",
        "emoji":    "🔴",
        "color":    0xE53935,
        "priority": 5,
    },
}

# Election + politics keywords (Nepali & English)
KEYWORDS = [
    # English
    "election", "2082", "vote", "voting", "ballot", "candidate", "constituency",
    "parliament", "result", "counting", "wins", "leads", "elected", "seat",
    "political", "politics", "party", "coalition", "government", "minister",
    "RSP", "UML", "Congress", "Balen", "Prachanda", "Ravi Lamichhane",
    # Nepali
    "निर्वाचन", "मतदान", "उम्मेद्वार", "चुनाव", "मत", "मतगणना",
    "प्रतिनिधिसभा", "संसद", "दल", "पार्टी", "गठबन्धन", "राजनीति",
    "नेकपा", "कांग्रेस", "रास्वपा", "एमाले", "सरकार", "मन्त्री",
]

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── BOT ──────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot     = commands.Bot(command_prefix="!", intents=intents)
seen: set = set()

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)

def uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_relevant(title: str, body: str = "") -> bool:
    text = (title + " " + body).lower()
    return any(k.lower() in text for k in KEYWORDS)

def clean_html(raw: str) -> str:
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ").strip()

async def get_og_image(session: aiohttp.ClientSession, url: str) -> str | None:
    """Scrape og:image from article — most reliable cross-site method."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200:
                return None
            html = await r.text(errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        # 1) og:image
        tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if tag and tag.get("content"):
            return tag["content"]
        # 2) twitter:image
        tag = soup.find("meta", attrs={"name": "twitter:image"})
        if tag and tag.get("content"):
            return tag["content"]
        # 3) first <img> in article body
        for sel in ["article img", ".post-content img", ".entry-content img", "figure img"]:
            img = soup.select_one(sel)
            if img and img.get("src"):
                src = img["src"]
                return src if src.startswith("http") else urljoin(url, src)
    except Exception as e:
        log.debug(f"Image scrape failed ({url}): {e}")
    return None

async def fetch_feed(session: aiohttp.ClientSession, name: str, cfg: dict) -> list[dict]:
    articles = []
    try:
        async with session.get(cfg["rss"], timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                log.warning(f"{name}: RSS {r.status}")
                return []
            xml = await r.text(errors="ignore")

        feed = feedparser.parse(xml)
        for e in feed.entries:
            title   = e.get("title", "").strip()
            link    = e.get("link", "").strip()
            summary = clean_html(e.get("summary", e.get("description", "")))[:350]
            pubdate = e.get("published", "")

            if not link or not title:
                continue
            if not is_relevant(title, summary):
                continue

            # Try to get image from RSS first
            img = None
            for mc in getattr(e, "media_content", []):
                if mc.get("url") and mc.get("type", "").startswith("image"):
                    img = mc["url"]
                    break
            if not img:
                for enc in getattr(e, "enclosures", []):
                    if enc.get("type", "").startswith("image"):
                        img = enc.get("href") or enc.get("url")
                        break

            articles.append({
                "title":   title,
                "link":    link,
                "summary": summary,
                "pub":     pubdate,
                "img":     img,
                "source":  name,
                "cfg":     cfg,
            })
    except Exception as ex:
        log.error(f"{name} feed error: {ex}")
    return articles

def make_embed(a: dict) -> discord.Embed:
    cfg    = a["cfg"]
    embed  = discord.Embed(
        title     = f"{cfg['emoji']} {a['title']}",
        url       = a["link"],
        color     = cfg["color"],
        timestamp = datetime.now(timezone.utc),
    )
    if a["summary"]:
        desc = a["summary"]
        embed.description = desc + ("…" if len(desc) >= 350 else "")
    embed.set_author(name=f"{a['source']}  •  Nepal Election 2082 🗳️")
    embed.set_footer(text=f"📅 {a['pub'] or 'Just now'}")
    if a.get("img"):
        embed.set_image(url=a["img"])
    return embed

# ─── BACKGROUND TASK ──────────────────────────────────────────────────────────

@tasks.loop(minutes=CHECK_INTERVAL)
async def poll():
    global seen
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.error("Channel not found — check CHANNEL_ID")
        return

    log.info(f"⏱ Polling {len(SOURCES)} sources...")
    posted = 0
    sorted_sources = sorted(SOURCES.items(), key=lambda x: x[1]["priority"])

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (compatible; NepalElectionBot/2.0)"}
    ) as session:
        for name, cfg in sorted_sources:
            articles = await fetch_feed(session, name, cfg)

            for a in articles:
                aid = uid(a["link"])
                if aid in seen:
                    continue
                seen.add(aid)

                # If no image from RSS, scrape the article page
                if not a["img"]:
                    a["img"] = await get_og_image(session, a["link"])

                try:
                    embed = make_embed(a)
                    await channel.send(embed=embed)
                    posted += 1
                    log.info(f"✅ [{name}] {a['title'][:70]}")
                    await asyncio.sleep(2)   # avoid Discord rate limits
                except discord.HTTPException as e:
                    log.error(f"Discord send failed: {e}")

    save_seen()
    if posted:
        log.info(f"📬 {posted} article(s) posted.")
    else:
        log.info("✔ No new articles.")

@poll.before_loop
async def before_poll():
    await bot.wait_until_ready()

# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global seen
    seen = load_seen()
    log.info(f"🤖 Logged in as {bot.user}")
    log.info(f"📡 Channel: {CHANNEL_ID} | Interval: {CHECK_INTERVAL}m | Seen: {len(seen)}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Nepal Election 2082 🇳🇵"
        )
    )
    poll.start()

# ─── COMMANDS ─────────────────────────────────────────────────────────────────

@bot.command(name="status")
async def cmd_status(ctx):
    """Show bot health and source list."""
    e = discord.Embed(title="🇳🇵 Nepal Election Bot — Status", color=0x009E60)
    src_list = "\n".join(
        f"{v['emoji']} **{k}** (priority {v['priority']})"
        for k, v in sorted(SOURCES.items(), key=lambda x: x[1]["priority"])
    )
    e.add_field(name="📰 Sources", value=src_list, inline=False)
    e.add_field(name="⏱ Check Interval", value=f"Every {CHECK_INTERVAL} min", inline=True)
    e.add_field(name="📦 Articles Tracked", value=str(len(seen)), inline=True)
    e.set_footer(text=f"Bot uptime since {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    await ctx.send(embed=e)

@bot.command(name="check")
@commands.has_permissions(administrator=True)
async def cmd_check(ctx):
    """Force a news check right now. (Admin only)"""
    msg = await ctx.send("🔍 Checking now…")
    await poll()
    await msg.edit(content="✅ Check complete!")

@bot.command(name="sources")
async def cmd_sources(ctx):
    """List all monitored news sources."""
    lines = [f"{v['emoji']} [{k}]({v['base']})" for k, v in SOURCES.items()]
    e = discord.Embed(
        title="📰 Monitored Sources",
        description="\n".join(lines),
        color=0x7B1FA2
    )
    await ctx.send(embed=e)

@bot.command(name="addkeyword")
@commands.has_permissions(administrator=True)
async def cmd_addkeyword(ctx, *, keyword: str):
    """Add a keyword to track. (Admin only)"""
    KEYWORDS.append(keyword.strip())
    await ctx.send(f"✅ Added keyword: `{keyword.strip()}`\nTotal keywords: {len(KEYWORDS)}")

# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌  DISCORD_TOKEN not set!")
        print("    export DISCORD_TOKEN='your_token'")
        print("    export CHANNEL_ID='your_channel_id'\n")
    elif CHANNEL_ID == 0:
        print("\n❌  CHANNEL_ID not set!")
        print("    export CHANNEL_ID='your_channel_id'\n")
    else:
        bot.run(DISCORD_TOKEN)
