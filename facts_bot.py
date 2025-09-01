import os, time, random, sqlite3, hashlib, json, requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- конфиг из ENV ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_KEY     = os.getenv("OPENAI_API_KEY")
POST_EVERY_MIN = int(os.getenv("POST_EVERY_MIN", "360"))   # вариант A: каждые 6 ч
POSTS_PER_RUN  = int(os.getenv("POSTS_PER_RUN", "1"))
CATEGORIES     = [s.strip() for s in os.getenv(
    "CATEGORIES", "Природа,Животные,Космос,История,Наука,Технологии,Рекорды"
).split(",") if s.strip()]
USE_IMAGES     = os.getenv("USE_IMAGES", "1") == "1"
IMAGE_SIZE     = os.getenv("IMAGE_SIZE", "1024x1024")

if not TELEGRAM_TOKEN or not CHAT_ID or not OPENAI_KEY:
    raise SystemExit("Проверь TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)

# --- анти-дубликаты ---
DB = "facts.sqlite3"
conn = sqlite3.connect(DB)
conn.execute("CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, created_at INTEGER)")
conn.commit()

def already_posted(key: str) -> bool:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    cur = conn.execute("SELECT 1 FROM posts WHERE id=?", (h,))
    if cur.fetchone():
        return True
    conn.execute("INSERT INTO posts(id, created_at) VALUES(?, strftime('%s','now'))", (h,))
    conn.commit()
    return False

def sanitize_hashtags(tags):
    out = []
    for t in (tags or [])[:4]:
        t = "".join(ch for ch in str(t) if ch.isalnum() or ch == "_")
        if t:
            out.append("#"+t)
    return " ".join(out)

def gen_fact(category: str) -> dict:
    prompt = f"""
Сгенерируй один интересный, правдоподобный факт о мире на русском.
Категория: {category}.
Формат: 2–4 коротких предложения, без эмодзи и ссылок.
Верни строго JSON с ключами: "title","body","tags".
Пример:
{{"title":"Почему фламинго розовые",
 "body":"Пищевые каротиноиды накапливаются в перьях, из-за чего птицы выглядят розовыми.",
 "tags":["животные","природа","факты"]}}
"""
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            max_tokens=250,
            temperature=0.6,
        )
        text = r.choices[0].message.content.strip()
        s, e = text.find("{"), text.rfind("}")
        data = json.loads(text[s:e+1]) if s != -1 and e != -1 else {}
    except Exception as ex:
        print("GPT text error:", ex)
        data = {}
    title = (data.get("title") or f"Факт: {category}")[:60].strip()
    body  = (data.get("body")  or "Не удалось сгенерировать.").strip()
    tags  = data.get("tags") or [category]
    if not isinstance(tags, list): tags = [str(tags)]
    tags = [str(t).strip() for t in tags if str(t).strip()]
    return {"title": title, "body": body, "tags": tags}

def gen_image(title: str, category: str) -> str:
    """Возвращает URL сгенерированной картинки или ''."""
    if not USE_IMAGES:
        return ""
    try:
        prompt = f"Иллюстрация по теме: {category}. {title}. Реалистичный стиль, без текста."
        resp = client.images.generate(model="gpt-image-1", prompt=prompt, size=IMAGE_SIZE)
        return resp.data[0].url or ""
    except Exception as ex:
        print("GPT image error:", ex)
        return ""

def post_text_to_telegram(title: str, body: str, tags: list):
    text = f"<b>{title}</b>\n{body}"
    ht = sanitize_hashtags(tags)
    if ht:
        text += f"\n\n{ht}"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                                 "disable_web_page_preview": True}, timeout=20)
    r.raise_for_status()

def post_photo_to_telegram(caption: str, photo_url: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    r = requests.post(url, data={"chat_id": CHAT_ID, "caption": caption,
                                 "photo": photo_url, "parse_mode": "HTML"}, timeout=30)
    r.raise_for_status()

def run_once():
    left, guard = POSTS_PER_RUN, 10
    while left > 0 and guard > 0:
        guard -= 1
        cat  = random.choice(CATEGORIES)
        fact = gen_fact(cat)
        key  = fact["title"] + "|" + fact["body"]
        if already_posted(key):
            continue

        caption = f"<b>{fact['title']}</b>\n{fact['body']}"
        ht = sanitize_hashtags(fact.get("tags", []))
        if ht:
            caption += f"\n\n{ht}"

        try:
            img_url = gen_image(fact["title"], cat)
            if img_url:
                post_photo_to_telegram(caption, img_url)
            else:
                post_text_to_telegram(fact["title"], fact["body"], fact.get("tags", []))
            left -= 1
        except Exception as ex:
            print("Post error:", ex)
            break

if __name__ == "__main__":
    print("Facts bot started")
    while True:
        run_once()
        time.sleep(POST_EVERY_MIN * 60)
