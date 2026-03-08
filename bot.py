"""
🇳🇵 Nepal Politics & Election Bot — FINAL
Sources : Onlinekhabar, Setopati
Topics  : Elections + Nepal politics only
Features: No past-news spam · Smart embed title · Images · 24/7
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
#  CONFIG  —  set these as environment variables in Railway
# ══════════════════════════════════════════════════════════════════════════════

DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHANNEL_ID     = int(os.getenv("CHANNEL_ID", "0"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))   # minutes

SEEN_FILE      = "seen.json"
CATCHUP_FLAG   = "catchup_done.flag"

# ══════════════════════════════════════════════════════════════════════════════
#  SOURCES  —  Onlinekhabar + Setopati only
# ══════════════════════════════════════════════════════════════════════════════

SOURCES = {
    "Onlinekhabar": {
        "rss"  : "https://www.onlinekhabar.com/feed",
        "base" : "https://www.onlinekhabar.com",
        "emoji": "🟠",
        "color": 0xF57C00,
    },
    "Setopati": {
        "rss"  : "https://www.setopati.com/feed",
        "base" : "https://www.setopati.com",
        "emoji": "⚪",
        "color": 0x546E7A,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
#  KEYWORD FILTER  —  Nepal politics + election only
#  Rule: keyword must appear in the article TITLE (not summary)
# ══════════════════════════════════════════════════════════════════════════════

ALLOW_KEYWORDS = [
    # ── Election-specific ────────────────────────────────────────────────────
    "निर्वाचन", "मतदान", "मतगणना", "मतपत्र", "उम्मेद्वार",
    "निर्वाचन आयोग", "निर्वाचन परिणाम", "निर्वाचित",
    "विजयी", "पराजित", "मतदाता", "प्रतिनिधिसभा निर्वाचन",
    "election", "election result", "vote count", "ballot",
    "elected", "voter turnout", "election commission", "2082",
    # ── Nepal politics ───────────────────────────────────────────────────────
    "राजनीति", "राजनीतिक", "गठबन्धन", "सरकार गठन", "संसद",
    "प्रधानमन्त्री", "मन्त्रिपरिषद", "विश्वासको मत", "अविश्वास",
    "नेकपा", "कांग्रेस", "रास्वपा", "एमाले", "माओवादी",
    "nepal politics", "prime minister nepal", "parliament nepal",
    "coalition", "cabinet nepal", "government formation",
    # ── Key political figures ────────────────────────────────────────────────
    "Rabi Lamichhane", "Ravi Lamichhane", "रबि लामिछाने", "रवि लामिछाने",
    "Sher Bahadur Deuba", "शेर बहादुर देउवा",
    "KP Sharma Oli", "केपी शर्मा ओली", "केपी ओली",
    "Prachanda", "प्रचण्ड", "पुष्पकमल दाहाल",
    "Balen Shah", "बालेन शाह",
    "Madhav Nepal", "माधव नेपाल",
]

# Articles are REJECTED even if a keyword matched
BLOCKLIST = [
    # off-topic Nepal news
    "बजेट", "budget", "भूकम्प", "earthquake", "बाढी", "flood",
    "दुर्घटना", "accident", "अपराध", "crime", "हत्या", "murder",
    "चोरी", "theft", "आगलागी", "fire",
    # sports
    "cricket", "football", "IPL", "खेल", "sports", "FIFA", "NBA",
    # entertainment
    "फिल्म", "film", "movie", "चलचित्र", "celebrity", "सिनेमा",
    # finance/economy (unless directly political)
    "सेयर", "share market", "stock", "gold price", "सुनको भाउ",
    # weather / health
    "मनसुन", "monsoon", "dengue", "डेंगु", "COVID",
]

# ══════════════════════════════════════════════════════════════════════════════
#  CATEGORY TAGGER  —  gives each article a smart label for the embed header
# ══════════════════════════════════════════════════════════════════════════════

def get_category(title: str) -> str:
    """Return a short category label based on what the article is about."""
    t = title.lower()

    election_words = ["निर्वाचन", "मतदान", "मतगणना", "election", "vote", "ballot",
                      "elected", "विजयी", "पराजित", "निर्वाचित", "2082"]
    result_words   = ["परिणाम", "result", "जिते", "हारे", "विजय", "wins", "wins seat"]
    coalition_words= ["गठबन्धन", "coalition", "alliance"]
    govt_words     = ["सरकार", "प्रधानमन्त्री", "मन्त्रिपरिषद", "cabinet",
                      "prime minister", "government formation"]
    parliament_words=["संसद", "parliament", "विश्वासको मत", "अविश्वास", "session"]
    party_words    = ["नेकपा", "कांग्रेस", "रास्वपा", "एमाले", "माओवादी",
                      "congress", "uml", "rsp", "party", "दल"]

    if any(w in t for w in result_words):
        return "🏆 Election Result"
    if any(w in t for w in election_words):
        return "🗳️ Election 2082"
    if any(w in t for w in coalition_words):
        return "🤝 Coalition"
    if any(w in t for w in govt_words):
        return "🏛️ Government"
    if any(w in t for w in parliament_words):
        return "📜 Parliament"
    if any(w in t for w in party_words):
        return "🚩 Party News"
    return "🇳🇵 Nepal Politics"

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
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
    """Strict: keyword must be in TITLE. Blocklist overrides everything."""
    t = title.lower()
    if any(b.lower() in t for b in BLOCKLIST):
        return False
    return any(k.lower() in t for k in ALLOW_KEYWORDS)


def clean_html(raw: str) -> str:
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ").strip()


async def get_image(session: aiohttp.ClientSession, url: str) -> str | None:
    """Try og:image → twitter:image → first article img."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200:
                return None
            html = await r.text(errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        for attr in [("property", "og:image"), ("name", "twitter:image"),
                     ("property", "og:image:url")]:
            tag = soup.find("meta", {attr[0]: attr[1]})
            if tag and tag.get("content"):
                return tag["content"]
        for sel in ["article img", ".post-content img", ".entry-content img", "figure img"]:
            img = soup.select_one(sel)
            if img and img.get("src"):
                src = img["src"]
                return src if src.startswith("http") else urljoin(url, src)
    except Exception as e:
        log.debug(f"Image fetch failed ({url}): {e}")
    return None


async def fetch_feed(session: aiohttp.ClientSession, name: str, cfg: dict) -> list[dict]:
    articles = []
    try:
        async with session.get(cfg["rss"], timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status != 200:
                log.warning(f"{name}: RSS returned {r.status}")
                return []
            xml = await r.text(errors="ignore")

        feed = feedparser.parse(xml)
        for e in feed.entries:
            title   = e.get("title", "").strip()
            link    = e.get("link", "").strip()
            summary = clean_html(e.get("summary", e.get("description", "")))[:300]
            pubdate = e.get("published", "")

            if not title or not link:
                continue
            if not is_relevant(title):
                continue

            # Image from RSS enclosure / media
            img = None
            for mc in getattr(e, "media_content", []):
                if mc.get("url") and "image" in mc.get("type", ""):
                    img = mc["url"]; break
            if not img:
                for enc in getattr(e, "enclosures", []):
                    if "image" in enc.get("type", ""):
                        img = enc.get("href") or enc.get("url"); break

            articles.append({
                "title"  : title,
                "link"   : link,
                "summary": summary,
                "pub"    : pubdate,
                "img"    : img,
                "source" : name,
                "cfg"    : cfg,
            })
    except Exception as ex:
        log.error(f"{name} feed error: {ex}")
    return articles


def make_embed(a: dict) -> discord.Embed:
    cfg      = a["cfg"]
    category = get_category(a["title"])   # smart label based on content

    embed = discord.Embed(
        title     = a["title"],
        url       = a["link"],
        color     = cfg["color"],
        timestamp = datetime.now(timezone.utc),
    )
    if a["summary"]:
        embed.description = a["summary"] + ("…" if len(a["summary"]) >= 300 else "")

    # Author line: "🟠 Onlinekhabar  |  🗳️ Election 2082"
    embed.set_author(name=f"{cfg['emoji']} {a['source']}   |   {category}")
    embed.set_footer(text=f"📅 {a['pub'] or 'Just published'}")

    if a.get("img"):
        embed.set_image(url=a["img"])
    return embed

# ══════════════════════════════════════════════════════════════════════════════
#  CATCH-UP  —  runs ONCE on first deploy, silently marks all current
#               articles as seen so nothing old gets posted
# ══════════════════════════════════════════════════════════════════════════════

async def catchup():
    global seen
    log.info("🔄 First run — catch-up mode (marking existing articles, no posts)…")
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (compatible; NepalPoliticsBot/3.0)"}
    ) as session:
        for name, cfg in SOURCES.items():
            arts = await fetch_feed(session, name, cfg)
            for a in arts:
                seen.add(uid(a["link"]))
            log.info(f"  📌 {name}: marked {len(arts)} existing articles")
    save_seen()
    open(CATCHUP_FLAG, "w").write("done")
    log.info("✅ Catch-up done — only NEW articles will post from now on!")

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN POLL LOOP
# ══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=CHECK_INTERVAL)
async def poll():
    global seen
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        log.error("Channel not found — double-check CHANNEL_ID")
        return

    log.info("⏱ Polling sources…")
    posted = 0

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (compatible; NepalPoliticsBot/3.0)"}
    ) as session:
        for name, cfg in SOURCES.items():
            articles = await fetch_feed(session, name, cfg)
            for a in articles:
                aid = uid(a["link"])
                if aid in seen:
                    continue
                seen.add(aid)

                # Scrape image from article page if RSS didn't provide one
                if not a["img"]:
                    a["img"] = await get_image(session, a["link"])

                try:
                    await channel.send(embed=make_embed(a))
                    posted += 1
                    log.info(f"✅ [{name}] {a['title'][:70]}")
                    await asyncio.sleep(1.5)
                except discord.HTTPException as e:
                    log.error(f"Discord error: {e}")

    save_seen()
    log.info(f"📬 Done — {posted} new article(s) posted.")


@poll.before_loop
async def before_poll():
    await bot.wait_until_ready()

# ══════════════════════════════════════════════════════════════════════════════
#  BOT EVENTS
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    global seen
    seen = load_seen()
    log.info(f"🤖 Logged in as {bot.user}")
    log.info(f"📡 Channel: {CHANNEL_ID} | Interval: every {CHECK_INTERVAL}m | Seen: {len(seen)}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Nepal Politics & Election 🇳🇵"
        )
    )
    if not os.path.exists(CATCHUP_FLAG):
        await catchup()
    poll.start()

# ══════════════════════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@bot.command(name="status")
async def cmd_status(ctx):
    """Show bot status."""
    e = discord.Embed(title="🇳🇵 Nepal Politics Bot — Status", color=0x009E60)
    e.add_field(
        name="📰 Sources",
        value="\n".join(f"{v['emoji']} **{k}**" for k, v in SOURCES.items()),
        inline=True,
    )
    e.add_field(name="⏱ Interval",        value=f"Every {CHECK_INTERVAL} min", inline=True)
    e.add_field(name="📦 Articles Tracked", value=str(len(seen)),               inline=True)
    e.add_field(
        name="🔍 Filtering",
        value=f"{len(ALLOW_KEYWORDS)} allow-keywords · {len(BLOCKLIST)} blocklist entries",
        inline=False,
    )
    await ctx.send(embed=e)


@bot.command(name="check")
@commands.has_permissions(administrator=True)
async def cmd_check(ctx):
    """Force an immediate news check. (Admin only)"""
    msg = await ctx.send("🔍 Checking now…")
    await poll()
    await msg.edit(content="✅ Done!")


@bot.command(name="addkeyword")
@commands.has_permissions(administrator=True)
async def cmd_addkeyword(ctx, *, keyword: str):
    """Add a keyword to the allow list. (Admin only)"""
    ALLOW_KEYWORDS.append(keyword.strip())
    await ctx.send(f"✅ Added: `{keyword.strip()}` — total: {len(ALLOW_KEYWORDS)}")


@bot.command(name="blockword")
@commands.has_permissions(administrator=True)
async def cmd_blockword(ctx, *, word: str):
    """Add a word to the blocklist. (Admin only)"""
    BLOCKLIST.append(word.strip())
    await ctx.send(f"🚫 Blocked: `{word.strip()}` — total blocklist: {len(BLOCKLIST)}")

# ══════════════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌  Set DISCORD_TOKEN environment variable first!")
    elif CHANNEL_ID == 0:
        print("\n❌  Set CHANNEL_ID environment variable first!")
    else:
        bot.run(DISCORD_TOKEN)
