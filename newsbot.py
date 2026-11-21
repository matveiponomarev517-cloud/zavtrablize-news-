
import os
import json
import hashlib
import sqlite3
import logging
import urllib.request
import urllib.error
import datetime
import time

import feedparser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB = os.getenv("DB_PATH", "news.db")
MAX_DAY = int(os.getenv("MAX_PER_DAY", "3"))
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@zavtrablize")
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
MODEL_OVERRIDE = os.getenv("GEMINI_MODEL", "")

RSS = [
    "https://www.sciencedaily.com/rss/all.xml",
    "https://www.nasa.gov/rss/dyn/breaking_news.rss",
    "https://www.esa.int/rssfeed/Our_Activities/Space_Science",
    "https://feeds.arstechnica.com/arstechnica/science",
    "https://www.sciencedaily.com/rss/top/science.xml",
]


def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS articles (
        id TEXT PRIMARY KEY, url TEXT, title TEXT, status TEXT,
        created TEXT, post TEXT, doc_url TEXT, error TEXT
    )""")
    c.commit()
    return c


def req(url, data=None, headers=None):
    r = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method="POST" if data else "GET"
    )
    with urllib.request.urlopen(r, timeout=40) as x:
        return x.read()


def tg(text):
    p = json.dumps({
        "chat_id": TG_CHANNEL,
        "text": text,
        "disable_web_page_preview": False
    }).encode()

    raw = req(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        p,
        {"Content-Type": "application/json"}
    )

    d = json.loads(raw)

    if not d.get("ok"):
        raise RuntimeError("Telegram API: " + str(d))

    return d["result"]["message_id"]


def digest(u):
    return hashlib.sha256(u.strip().encode()).hexdigest()


def get_models():
    raw = req(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}"
    )
    data = json.loads(raw)

    available = [
        m["name"].replace("models/", "")
        for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]

    if MODEL_OVERRIDE:
        if MODEL_OVERRIDE in available:
            return MODEL_OVERRIDE
        raise RuntimeError("Configured Gemini model unavailable: " + MODEL_OVERRIDE)

    # Prefer Flash Lite, then Flash. Exclude experimental models where possible.
    lite = [
        x for x in available
        if "flash-lite" in x.lower() and "embedding" not in x.lower()
    ]
    flash = [
        x for x in available
        if "flash" in x.lower()
        and "lite" not in x.lower()
        and "embedding" not in x.lower()
    ]

    for group in (lite, flash):
        stable = [x for x in group if "preview" not in x.lower()]
        if stable:
            return stable[0]
        if group:
            return group[0]

    raise RuntimeError("No supported Gemini Flash model found via ListModels")


def generate(model, title, url, summary):
    prompt = f"""Ты редактор научно-технологического канала «Завтра ближе».
Используй только переданные данные. Не выдумывай факты.
Не представляй пресс-релиз как независимую проверку.
Отсекай слабое, рекламное, неподтверждённое и повторное.

Верни строго JSON:
publish: boolean
reason: string
headline: до 100 символов
post: русский Telegram-пост 600-1300 символов,
без кликбейта, с URL источника
article: статья 1500-3500 символов,
с осторожными формулировками и источником.

Заголовок: {title}
URL: {url}
Описание: {summary}"""

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }).encode()

    raw = req(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}",
        body,
        {"Content-Type": "application/json"}
    )

    data = json.loads(raw)
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def alert(msg):
    admin = os.getenv("TELEGRAM_ADMIN_ID")
    if admin:
        try:
            req(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json.dumps({
                    "chat_id": admin,
                    "text": msg[:3500]
                }).encode(),
                {"Content-Type": "application/json"}
            )
        except Exception:
            logging.exception("Alert delivery failed")


def main():
    c = db()
    errors = []
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()

    n = c.execute(
        "SELECT COUNT(*) FROM articles WHERE status='published' AND created LIKE ?",
        (today + "%",)
    ).fetchone()[0]

    if n >= MAX_DAY:
        logging.info("Daily publication limit reached")
        return

    model = get_models()
    logging.info("Selected Gemini model: %s", model)

    candidates = []

    for feed in RSS:
        try:
            f = feedparser.parse(feed)

            for e in f.entries[:15]:
                url = e.get("link", "").strip()
                title = e.get("title", "").strip()

                if not url or not title:
                    continue

                uid = digest(url)

                if c.execute(
                    "SELECT 1 FROM articles WHERE id=?", (uid,)
                ).fetchone():
                    continue

                stamp = e.get("published_parsed") or e.get("updated_parsed")

                if stamp:
                    dt = datetime.datetime(*stamp[:6], tzinfo=datetime.timezone.utc)

                    if (now - dt).days > 14 or dt > now + datetime.timedelta(hours=1):
                        continue

                    age = dt.timestamp()
                else:
                    age = 0

                candidates.append((
                    age, uid, url, title, e.get("summary", "")
                ))

        except Exception as ex:
            logging.exception("Feed error: %s", feed)
            errors.append("RSS " + feed + ": " + str(ex))

    candidates.sort(reverse=True)

    for _, uid, url, title, summary in candidates[:3]:
        if n >= MAX_DAY:
            break

        created = now.isoformat()

        c.execute(
            "INSERT OR IGNORE INTO articles VALUES(?,?,?,?,?,?,?,?)",
            (uid, url, title, "processing", created, None, None, None)
        )
        c.commit()

        try:
            result = generate(model, title, url, summary)

            if not result.get("publish"):
                c.execute(
                    "UPDATE articles SET status='rejected',error=? WHERE id=?",
                    (result.get("reason", "filtered")[:500], uid)
                )
                c.commit()
                logging.info("Rejected: %s", title)
                continue

            post = result.get("post", "").strip()
            headline = result.get("headline", "").strip()
            article = result.get("article", "").strip()

            if not post or not headline or not article:
                raise ValueError("Generated content incomplete")

            if len(post) > 3900:
                raise ValueError("Telegram post too long")

            if url not in post:
                post += "\n\nИсточник: " + url

            c.execute(
                "UPDATE articles SET status='ready',post=? WHERE id=?",
                (post, uid)
            )
            c.commit()

            message_id = tg(post)

            c.execute(
                "UPDATE articles SET status='published',error=? WHERE id=?",
                ("telegram_message_id=" + str(message_id), uid)
            )
            c.commit()

            n += 1
            logging.info("Published: %s", headline)

        except Exception as ex:
            c.execute(
                "UPDATE articles SET status='error',error=? WHERE id=?",
                (str(ex)[:1000], uid)
            )
            c.commit()

            logging.exception("Processing failure")
            errors.append(title + ": " + str(ex))
            alert("⚠️ «Завтра ближе»\n" + title + "\n" + str(ex))

    if errors:
        raise RuntimeError(
            "Errors during execution: " + " | ".join(errors[:5])
        )


if __name__ == "__main__":
    main()
 
