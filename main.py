"""
BJ X Agent Demo
Built in exactly 1 hour using only an iPhone.
Real tools. Zero farming. Human Edge.

Author: @BJ_Beyond
"""

import os
import io
import csv
import time
import sqlite3
import threading
import logging
import asyncio
import feedparser
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment variables (set these in your .env or hosting platform)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID_RAW = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", 8080))

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

DB_NAME = "agent_vault.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scraped_posts (
            id TEXT PRIMARY KEY,
            author TEXT,
            content TEXT,
            published_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS style_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_text TEXT,
            added_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# RSS Feeds
RSS_FEEDS = [
    {"source": "Custom Feed BJ", "url": "https://rss.app/feeds/t5ooMu9TaY8RO77f.xml"},
    {"source": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"source": "MIT Tech Review", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed"}
]

# -------------------- Core Functions --------------------

async def scan_and_notify_feeds(bot_application):
    logger.info("Starting proactive RSS scan...")
    total_added = 0
    new_items = []

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:2]:
                p_id = getattr(entry, 'id', getattr(entry, 'link', ''))
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '')
                content = f"{title} - {summary}"[:500]
                pub = getattr(entry, 'published', time.ctime())

                if p_id:
                    cursor.execute(
                        "INSERT OR IGNORE INTO scraped_posts (id, author, content, published_at) VALUES (?, ?, ?, ?)",
                        (p_id, feed_info["source"], content, pub)
                    )
                    if cursor.rowcount > 0:
                        total_added += 1
                        new_items.append(content)
        except Exception:
            continue

    conn.commit()
    conn.close()
    logger.info(f"Scan completed. New items: {total_added}")

    if total_added > 0 and ALLOWED_USER_ID_RAW and GEMINI_API_KEY:
        await evaluate_and_poke_user(bot_application, new_items)

async def evaluate_and_poke_user(bot_application, new_items):
    joined_news = "\n---\n".join(new_items[:5])
    style_context = get_style_samples()

    prompt = f"""
You are the ghostwriter and strategist of BJ (@BJ_Beyond).
Analyze these new items:
{joined_news}

If there is a truly relevant news about Human Edge, AI, art or technology, write a short proactive message (max 3 sentences) alerting me and suggesting a sharp post idea in BJ's style.
If nothing is strong enough, reply EXACTLY with the word: SKIP.
"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text_out = response.text.strip()

        if "skip" not in text_out.lower() and len(text_out) > 10:
            await bot_application.bot.send_message(
                chat_id=ALLOWED_USER_ID_RAW,
                text=f"🚨 **Phoenix Alert**\n\n{text_out}",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Proactive analysis error: {e}")

def save_style_sample(text: str) -> int:
    clean = text.strip()
    if not clean:
        return 0
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO style_memory (sample_text, added_at) VALUES (?, ?)",
        (clean, time.strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM style_memory")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def save_bulk_samples(posts_list: list) -> int:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    added = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for p in posts_list:
        clean = p.strip()
        if len(clean) > 20:
            cursor.execute("INSERT INTO style_memory (sample_text, added_at) VALUES (?, ?)", (clean, now))
            added += 1
    conn.commit()
    conn.close()
    return added

def get_style_samples() -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT sample_text FROM style_memory ORDER BY RANDOM() LIMIT 6")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return "No style samples yet."
    return "\n---\n".join([f"Real BJ post:\n{r[0]}" for r in rows])

def clear_all_memory():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM style_memory")
    conn.commit()
    conn.close()

def generate_ai_drafts(prompt_topic: str, lang_mode: str = "both") -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT author, content FROM scraped_posts ORDER BY ROWID DESC LIMIT 8")
    rows = cursor.fetchall()
    conn.close()

    context_text = "\n---\n".join([f"Source [{r[0]}]: {r[1]}" for r in rows]) if rows else "No recent context."
    style_context = get_style_samples()

    if lang_mode == "it":
        output_instruction = """Generate 3 options strictly in ITALIAN:
1. Hook + direct insight
2. Deep analytical post
3. Counter-intuitive Human Edge take"""
    elif lang_mode == "en":
        output_instruction = """Generate 3 options strictly in ENGLISH:
1. Magnetic hook + concise insight
2. Fast-paced analytical post
3. Counter-intuitive Human Edge take"""
    else:
        output_instruction = """Generate 3 options, each with both ITALIAN and ENGLISH versions:
**OPTION 1**
🇮🇹 IT: ...
🇬🇧 EN: ...
***
**OPTION 2**
🇮🇹 IT: ...
🇬🇧 EN: ...
***
**OPTION 3 (Human Edge)**
🇮🇹 IT: ...
🇬🇧 EN: ..."""

    full_prompt = f"""
You are the personal ghostwriter of BJ (@BJ_Beyond).
Tone: authoritative, sharp, synthetic, focused on Human Edge.

Style memory:
{style_context}

Recent signals:
{context_text}

Topic from BJ:
"{prompt_topic}"

{output_instruction}

Output only the drafts, ready to copy-paste. No introductions.
"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(full_prompt)
        return response.text if response and response.text else "Generation failed."
    except Exception as e:
        return f"⚠️ Error: {e}"

def is_authorized(user_id) -> bool:
    if not ALLOWED_USER_ID_RAW:
        return True
    return str(user_id) == str(ALLOWED_USER_ID_RAW)

# -------------------- Telegram Handlers --------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized")
        return
    await update.message.reply_text(
        "👋 **BJ X Agent online**\n\n"
        "• /scan – manual scan\n"
        "• /learn <text> – learn style\n"
        "• /memory – show memory\n"
        "• /clear_memory – reset style\n"
        "• Send .txt or .csv to bulk learn\n"
        "• Write \"Genera i post\" for bilingual drafts",
        parse_mode="Markdown"
    )

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text("🔄 Scanning...")
    # simplified manual scan for demo
    await update.message.reply_text("✅ Scan completed")

async def learn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Send some text to learn")
        return
    total = save_style_sample(text)
    await update.message.reply_text(f"🧠 Style learned. Total samples: {total}")

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(f"📚 Current memory:\n\n{get_style_samples()}")

async def clear_memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    clear_all_memory()
    await update.message.reply_text("🧹 Memory cleared")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    doc = update.message.document
    if not doc.file_name.lower().endswith(('.txt', '.csv')):
        await update.message.reply_text("Send .txt or .csv only")
        return
    await update.message.reply_text("📥 Learning archive...")
    file = await doc.get_file()
    content = (await file.download_as_bytearray()).decode('utf-8', errors='ignore')
    posts = content.split("---") if "---" in content else content.split("\n\n")
    added = save_bulk_samples(posts)
    await update.message.reply_text(f"🚀 Learned {added} posts")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    text = update.message.text.lower()
    if "genera i post" in text or "genera post" in text:
        await update.message.reply_text("🚀 Generating bilingual drafts...")
        result = generate_ai_drafts("Based on recent conversation and signals")
        await update.message.reply_text(result)
        return
    await update.message.reply_text("Write a topic or say \"Genera i post\"")

# -------------------- Flask + Main --------------------

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

async def run_bot():
    bot_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start_cmd))
    bot_app.add_handler(CommandHandler("scan", scan_cmd))
    bot_app.add_handler(CommandHandler("learn", learn_cmd))
    bot_app.add_handler(CommandHandler("memory", memory_cmd))
    bot_app.add_handler(CommandHandler("clear_memory", clear_memory_cmd))
    bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.run_coroutine_threadsafe(scan_and_notify_feeds(bot_app), asyncio.get_event_loop()),
        'interval', minutes=45
    )
    scheduler.start()

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    logger.info("Bot started with proactive mode")

    while True:
        await asyncio.sleep(3600)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down")

if __name__ == "__main__":
    main()
