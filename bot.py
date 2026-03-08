"""
🇳🇵 Nepal Politics & Election Bot — FINAL v3
News Sources  : Onlinekhabar (blue), Setopati (grey), Techpana (lime)
Factcheck     : Techpana Factcheck → separate Discord channel
Topics        : Nepal elections + politics only (news channel)
               All Techpana factcheck posts (factcheck channel)
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
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — set all of these as environment variables in Railway
# ══════════════════════════════════════════════════════════════════════════════

DISCORD_TOKEN        = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
NEWS_CHANNEL_ID      = int(os.getenv("CHANNEL_ID", "0"))
FACTCHECK_CHANNEL_ID = int(os.getenv("FACTCHECK_CHANNEL_ID", "0"))
CHECK_INTERVAL       = int(os.getenv("CHECK_INTERVAL", "5"))

SEEN_FILE    = "seen.json"
CATCHUP_FLAG = "catchup_done.flag"

# ══════════════════════════════════════════════════════════════════════════════
#  NEWS SOURCES
# ══════════════════════════════════════════════════════════════════════════════

NEWS_SOURCES = {
    "Onlinekhabar": {
        "rss"  : "https://www.onlinekhabar.com/feed",
        "base" : "https://www.onlinekhabar.com",
        "emoji": "🔵",
        "color": 0x1A6FD4,
    },
    "Setopati": {
        "rss"  : "https://www.setopati.com/feed",
        "base" : "https://www.setopati.com",
        "emoji": "⚪",
        "color": 0x546E7A,
    },
    "Techpana": {
        "rss"  : "https://techpana.com/rss",
        "base" : "https://techpana.com",
        "emoji": "🟢",
        "color": 0x84CC16,
    },
}

FACTCHECK_SOURCE = {
    "rss"  : "https://techpana.com/rss",
    "emoji": "🔍",
    "color": 0x84CC16,
}

# ══════════════════════════════════════════════════════════════════════════════
#  FILTERS
# ══════════════════════════════════════════════════════════════════════════════

ALLOW_KEYWORDS = [
    "निर्वाचन", "मतदान", "मतगणना", "मतपत्र", "उम्मेद्वार",
    "निर्वाचन आयोग", "निर्वाचन परिणाम", "निर्वाचित",
    "विजयी", "पराजित", "मतदाता", "प्रतिनिधिसभा निर्वाचन",
    "election", "election result", "vote count", "ballot",
    "elected", "voter turnout", "election commission", "2082",
    "राजनीति", "राजनीतिक", "गठबन्धन", "सरकार गठन", "संसद",
    "प्रधानमन्त्री", "मन्त्रिपरिषद", "विश्वासको मत", "अविश्वास",
    "नेकपा", "कांग्रेस", "रास्वपा", "एमाले", "माओवादी",
    "nepal politics", "prime minister nepal", "parliament nepal",
    "coalition", "cabinet nepal", "government formation",
    "Rabi Lamichhane", "Ravi Lamichhane", "रबि लामिछाने", "रवि लामिछाने",
    "Sher Bahadur Deuba", "शेर बहादुर देउवा",
    "KP Sharma Oli", "केपी शर्मा ओली", "केपी ओली",
    "Prachanda", "प्रचण्ड", "पुष्पकमल दाहाल",
    "Balen Shah", "बालेन शाह",
    "Madhav Nepal", "माधव नेपाल",
]

BLOCKLIST = [
    "बजेट", "budget", "भूकम्प", "earthquake", "बाढी", "flood",
    "दुर्घटना", "accident", "अपराध", "crime", "हत्या", "murder",
    "चोरी", "theft", "आगलागी", "fire",
    "cricket", "football", "IPL", "खेल", "sports", "FIFA",
    "फिल्म", "film", "movie", "चलचित्र", "celebrity", "सिनेमा",
    "सेयर", "share market", "stock", "gold price", "सुनको भाउ",
    "मनसुन", "monsoon", "dengue", "डेंगु",
    "smartphone", "iphone", "android", "laptop", "gadget",
    "price in nepal", "review", "specification",
]

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORY TAGGER
# ══════════════════════════════════════════════════════════════════════════════

def get_category(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["परिणाम", "result", "जिते", "हारे", "विजय", "wins"]):
        return "🏆 Election Result"
    if any(w in t for w in ["निर्वाचन", "मतदान", "मतगणना", "election", "vote", "ballot", "2082"]):
        return "🗳️ Election 2082"
    if any(w in t for w in ["गठबन्धन", "coalition", "alliance"]):
        return "🤝 Coalition"
    if any(w in t for w in ["सरकार", "प्रधानमन्त्री", "मन्त्रिपरिषद", "cabinet", "prime minister"]):
        return "🏛️ Government"
    if any(w in t for w in ["संसद", "parliament", "विश्वासको मत", "अविश्वास"]):
        return "📜 Parliament"
    if any(w in t for w in ["नेकपा", "कांग्रेस", "रास्वपा", "एमाले", "माओवादी", "party", "दल"]):
        return "🚩 Party News"
    return "🇳🇵 Nepal Politics"

# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING + BOT
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

intents = discord.Intents.all()
bot     = commands.Bot(command_prefix="!", intents=intents)
seen: set = set()

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

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
        json.dump(list(seen)[-5000:], f)

def uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(b.lower() in t for b in BLOCKLIST):
        return False
    return any(k.lower() in t for k in ALLOW_KEYWORDS)

def clean_html(raw: str) -> str:
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ").strip()

async def get_image(session: aiohttp.ClientSession, url: str):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200:
                return None
            html = await r.text(errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        for attr in [("property", "og:image"), ("name", "twitter:image")]:
            tag = soup.find("meta", {attr[0]: attr[1]})
            if tag and tag.get("content"):
                return tag["content"]
        for sel in ["article img", ".post-content img", "figure img"]:
            img = soup.select_one(sel)
            if img and img.get("src"):
                src = img["src"]
                return src if src.startswith("http") else urljoin(url, src)
    except Exception as e:
        log.debug(f"Image fetch failed ({url}): {e}")
    return None

async def fetch_feed(session: aiohttp.ClientSession, rss_url: str) -> list:
    try:
        async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                log.warning(f"RSS {rss_url} → {r.status}")
                return []
            xml = await r.text(errors="ignore")
        results = []
        for e in feedparser.parse(xml).entries:
            title   = e.get("title", "").strip()
            link    = e.get("link", "").strip()
            summary = clean_html(e.get("summary", e.get("description", "")))[:300]
            pubdate = e.get("published", "")
            if not title or not link:
                continue
            img = None
            for mc in getattr(e, "media_content", []):
                if mc.get("url") and "image" in mc.get("type", ""):
                    img = mc["url"]; break
            if not img:
                for enc in getattr(e, "enclosures", []):
                    if "image" in enc.get("type", ""):
                        img = enc.get("href") or enc.get("url"); break
            results.append({"title": title, "link": link, "summary": summary, "pub": pubdate, "img": img})
        return results
    except Exception as ex:
        log.error(f"Feed error ({rss_url}): {ex}")
        return []

def make_news_embed(a: dict, name: str, cfg: dict) -> discord.Embed:
    embed = discord.Embed(title=a["title"], url=a["link"], color=cfg["color"], timestamp=datetime.now(timezone.utc))
    if a["summary"]:
        embed.description = a["summary"] + ("…" if len(a["summary"]) >= 300 else "")
    embed.set_author(name=f"{cfg['emoji']} {name}   |   {get_category(a['title'])}")
    embed.set_footer(text=f"📅 {a['pub'] or 'Just published'}")
    if a.get("img"):
        embed.set_image(url=a["img"])
    return embed

def make_factcheck_embed(a: dict) -> discord.Embed:
    cfg   = FACTCHECK_SOURCE
    embed = discord.Embed(title=a["title"], url=a["link"], color=cfg["color"], timestamp=datetime.now(timezone.utc))
    if a["summary"]:
        embed.description = a["summary"] + ("…" if len(a["summary"]) >= 300 else "")
    embed.set_author(name=f"{cfg['emoji']} Techpana   |   ✅ Fact Check")
    embed.set_footer(text=f"📅 {a['pub'] or 'Just published'}")
    if a.get("img"):
        embed.set_image(url=a["img"])
    return embed

# ══════════════════════════════════════════════════════════════════════════════
#  CATCH-UP
# ══════════════════════════════════════════════════════════════════════════════

async def catchup():
    global seen
    log.info("🔄 First run — catch-up mode…")
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        for name, cfg in NEWS_SOURCES.items():
            arts = await fetch_feed(session, cfg["rss"])
            for a in arts:
                seen.add(uid(a["link"]))
            log.info(f"  📌 {name}: {len(arts)} articles marked")
        arts = await fetch_feed(session, FACTCHECK_SOURCE["rss"])
        for a in arts:
            seen.add(uid(a["link"]))
        log.info(f"  📌 Techpana Factcheck: {len(arts)} articles marked")
    save_seen()
    open(CATCHUP_FLAG, "w").write("done")
    log.info("✅ Catch-up done — only NEW articles will post!")

# ══════════════════════════════════════════════════════════════════════════════
#  POLL LOOP
# ══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=CHECK_INTERVAL)
async def poll():
    global seen
    news_ch     = bot.get_channel(NEWS_CHANNEL_ID)
    factcheck_ch = bot.get_channel(FACTCHECK_CHANNEL_ID)
    if not news_ch:
        log.error("News channel not found — check CHANNEL_ID"); return

    log.info("⏱ Polling…")
    pn = pf = 0

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # News
        for name, cfg in NEWS_SOURCES.items():
            for a in await fetch_feed(session, cfg["rss"]):
                if not is_relevant(a["title"]): continue
                aid = uid(a["link"])
                if aid in seen: continue
                seen.add(aid)
                if not a["img"]:
                    a["img"] = await get_image(session, a["link"])
                try:
                    await news_ch.send(embed=make_news_embed(a, name, cfg))
                    pn += 1
                    log.info(f"✅ [NEWS/{name}] {a['title'][:70]}")
                    await asyncio.sleep(1.5)
                except discord.HTTPException as e:
                    log.error(f"Discord error: {e}")

        # Factcheck — only articles that are actually factchecks
        # Techpana uses /factcheck/ in URL or "fact check"/"factcheck" in title
        def is_factcheck(a):
            link_lower  = a["link"].lower()
            title_lower = a["title"].lower()
            return ("factcheck" in link_lower or "fact-check" in link_lower or
                    "fact check" in title_lower or "factcheck" in title_lower or
                    "फ्याक्ट" in a["title"] or "तथ्यजाँच" in a["title"])

        if factcheck_ch:
            for a in await fetch_feed(session, FACTCHECK_SOURCE["rss"]):
                if not is_factcheck(a): continue   # skip non-factcheck articles
                aid = uid(a["link"])
                if aid in seen: continue
                seen.add(aid)
                if not a["img"]:
                    a["img"] = await get_image(session, a["link"])
                try:
                    await factcheck_ch.send(embed=make_factcheck_embed(a))
                    pf += 1
                    log.info(f"✅ [FACTCHECK] {a['title'][:70]}")
                    await asyncio.sleep(1.5)
                except discord.HTTPException as e:
                    log.error(f"Discord error: {e}")

    save_seen()
    log.info(f"📬 {pn} news · {pf} factcheck posted.")

@poll.before_loop
async def before_poll():
    await bot.wait_until_ready()

# ══════════════════════════════════════════════════════════════════════════════
#  EVENTS + COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    global seen
    seen = load_seen()
    log.info(f"🤖 {bot.user} | News: {NEWS_CHANNEL_ID} | Factcheck: {FACTCHECK_CHANNEL_ID}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Nepal Politics & Election 🇳🇵"))
    if not os.path.exists(CATCHUP_FLAG):
        await catchup()
    poll.start()

@bot.command(name="status")
async def cmd_status(ctx):
    e = discord.Embed(title="🇳🇵 Nepal Politics Bot", color=0x009E60)
    src = "\n".join(f"{v['emoji']} **{k}**" for k, v in NEWS_SOURCES.items())
    src += f"\n🔍 **Techpana Factcheck** (→ factcheck channel)"
    e.add_field(name="📰 Sources",          value=src,                         inline=False)
    e.add_field(name="⏱ Interval",         value=f"Every {CHECK_INTERVAL}m",  inline=True)
    e.add_field(name="📦 Articles Tracked", value=str(len(seen)),              inline=True)
    await ctx.send(embed=e)

@bot.command(name="check")
@commands.has_permissions(administrator=True)
async def cmd_check(ctx):
    msg = await ctx.send("🔍 Checking…")
    await poll()
    await msg.edit(content="✅ Done!")

@bot.command(name="addkeyword")
@commands.has_permissions(administrator=True)
async def cmd_addkeyword(ctx, *, keyword: str):
    ALLOW_KEYWORDS.append(keyword.strip())
    await ctx.send(f"✅ Added: `{keyword.strip()}`")

@bot.command(name="blockword")
@commands.has_permissions(administrator=True)
async def cmd_blockword(ctx, *, word: str):
    BLOCKLIST.append(word.strip())
    await ctx.send(f"🚫 Blocked: `{word.strip()}`")

# ══════════════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Set DISCORD_TOKEN!")
    elif NEWS_CHANNEL_ID == 0:
        print("❌  Set CHANNEL_ID!")
    elif FACTCHECK_CHANNEL_ID == 0:
        print("❌  Set FACTCHECK_CHANNEL_ID!")
    else:
        bot.run(DISCORD_TOKEN)
