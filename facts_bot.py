import os, time, random, sqlite3, hashlib, json, requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
POST_EVERY_MIN = int(os.getenv("POST_EVERY_MIN", "180"))
POSTS_PER_RUN = int(os.getenv("POSTS_PER_RUN", "1"))
CATEGORIES = [s.strip() for s in os.getenv(
    "CATEGORIES", "Природа,Животные,Космос,История,Наука,Технологии,Рекорды"
).split(",") if s.strip()]

if not TELEGRAM_TOKEN or not CHAT_ID or not OPENAI_KEY:
    raise SystemExit("Заполни TELEGRAM_BOT_TOKEN, CHAT_ID и OPENAI_API_KEY в .env")

client = OpenAI(api_key=OPENAI_KEY)

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

def gen_fact(category: str) -> dict:
    prompt = f"""
Сгенерируй один интересный факт о мире на русском языке.
Категория: {category}.
Формат: 2–4 предложения, без эмодзи и клише.
Верни JSON с ключами title, body, tags.
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            max_tokens=250,
            temperature=0.6
        )
        text = resp.choices[0].message.content.strip()
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end+1])
    except:
        return {"title": f"Факт: {category}", "body": "Не удалось сгенерировать.", "tags":[category]}

def post_to_telegram(title: str, body: str, tags: list):
    text = f"<b>{title}</b>\n{body}"
    if tags:
        text += "\n\n" + " ".join("#"+t for t in tags[:4])
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    requests.post(url, json=payload)

def run_once():
    left = POSTS_PER_RUN
    while left > 0:
        cat = random.choice(CATEGORIES)
        fact = gen_fact(cat)
        key = fact["title"] + "|" + fact["body"]
        if already_posted(key):
            continue
        post_to_telegram(fact["title"], fact["body"], fact.get("tags", []))
        left -= 1

if __name__ == "__main__":
    print("Бот запущен")
    while True:
        run_once()
        time.sleep(POST_EVERY_MIN * 60)
