import asyncio
import random
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import sqlite3
import xml.etree.ElementTree as ET

# === Конфигурация ===
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

SITEMAP_FILE = "sitemap2.xml"
DONE_FILE = Path("done_lenta.txt")
DEAD_FILE = Path("dead_links_lenta.txt")
DB_PATH = "lenta.db"
REQUEST_TIMEOUT = 15
NUM_WORKERS = 20
DELAY_RANGE = (2, 3)

client: httpx.AsyncClient


# === Парсинг XML sitemap ===
def load_urls_from_sitemap(filepath: str) -> list[str]:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    # Удаляем namespace, если есть
    content = re.sub(r' xmlns="[^"]+"', '', content, count=1)
    root = ET.fromstring(content)

    urls = []
    for url_tag in root.findall(".//url"):
        loc = url_tag.find("loc")
        if loc is not None and loc.text:
            url = loc.text.strip()
            if url:
                urls.append(url)
    return urls


# === Инициализация БД ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            guid TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            url TEXT UNIQUE,
            published_at TEXT,
            comments_count INTEGER,
            created_at_utc TEXT,
            rating INTEGER
        )
    """)
    conn.commit()
    conn.close()


# === Сохранение статьи ===
def save_article(data):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO articles
        (guid, title, description, url, published_at, comments_count, created_at_utc, rating)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["guid"],
        data["title"],
        data["description"],
        data["url"],
        data["published_at"],
        data["comments_count"],
        data["created_at_utc"],
        data["rating"]
    ))
    conn.commit()
    conn.close()


# === Очистка текста ===
def clean_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "lxml")
    for tag in soup.select("img, video, audio, iframe, figure, script, style, .topic-body__content-foot"):
        tag.decompose()
    # Извлекаем только <p> с текстом
    paragraphs = soup.select("p.topic-body__content-text")
    text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
    return text.strip()


# === Парсинг даты из строки вида "15:37, 10 октября 2012" ===
def parse_lenta_date(date_str: str) -> str | None:
    ru_months = {
        "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
        "мая": "05", "июня": "06", "июля": "07", "августа": "08",
        "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"
    }
    for ru, num in ru_months.items():
        date_str = date_str.replace(ru, num)
    try:
        dt = datetime.strptime(date_str, "%H:%M, %d %m %Y")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


# === Парсинг статьи с lenta.ru ===
def parse_article(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    # Заголовок
    title_span = soup.select_one("h1.topic-body__titles > span.topic-body__title")
    if not title_span:
        print(f"  → Пропущено: нет заголовка на {url}")
        return None
    title = title_span.get_text(strip=True)
    if not title:
        print(f"  → Пропущено: пустой заголовок на {url}")
        return None

    # Текст
    content_div = soup.select_one("div.topic-body__content.js-topic-body-content")
    if not content_div:
        print(f"  → Пропущено: нет контейнера текста на {url}")
        return None

    description = clean_text(str(content_div))
    if not description:
        print(f"  → Пропущено: текст пуст на {url}")
        return None

    # Дата
    time_tag = soup.select_one("a.topic-header__item.topic-header__time")
    published_at = None
    if time_tag:
        date_text = time_tag.get_text(strip=True)
        published_at = parse_lenta_date(date_text)

    return {
        "guid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "url": url,
        "published_at": published_at,
        "comments_count": 0,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "rating": 0
    }


# === Воркер ===
async def worker(worker_id: int, url_queue: asyncio.Queue):
    while not url_queue.empty():
        url = await url_queue.get()
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            resp = await client.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 404:
                print(f"[{worker_id}] 404 — мёртвая ссылка: {url}")
                with open(DEAD_FILE, "a", encoding="utf-8") as f:
                    f.write(url + "\n")
                url_queue.task_done()
                continue

            if resp.status_code != 200:
                print(f"[{worker_id}] HTTP {resp.status_code} — {url}")
                url_queue.task_done()
                continue

            article = parse_article(resp.text, url)
            if article:
                save_article(article)
                print(f"[{worker_id}] Сохранено: {article['title'][:40]}... {article['url']}")
            else:
                print(f"[{worker_id}] Пропущено (пусто): {url}")

            with open(DONE_FILE, "a", encoding="utf-8") as f:
                f.write(url + "\n")

        except Exception as e:
            print(f"[{worker_id}] Ошибка на {url}: {e}")

        delay = random.uniform(*DELAY_RANGE)
        await asyncio.sleep(delay)
        url_queue.task_done()


# === Главная функция ===
async def main():
    global client
    init_db()

    # Загрузка URL из XML
    all_urls = load_urls_from_sitemap(SITEMAP_FILE)
    unique_urls = list(dict.fromkeys(all_urls))
    print(f"📥 Всего уникальных URL из sitemap: {len(unique_urls)}")

    # Прогресс
    done = set(DONE_FILE.read_text().splitlines()) if DONE_FILE.exists() else set()
    dead = set(DEAD_FILE.read_text().splitlines()) if DEAD_FILE.exists() else set()

    to_process = [url for url in unique_urls if url not in done and url not in dead]
    print(f"⏳ К обработке: {len(to_process)} ссылок")

    if not to_process:
        print("✅ Всё уже обработано.")
        return

    # Очередь
    queue = asyncio.Queue()
    for url in to_process:
        queue.put_nowait(url)

    # Запуск
    async with httpx.AsyncClient(http2=True, timeout=REQUEST_TIMEOUT) as client:
        workers = [
            asyncio.create_task(worker(i + 1, queue))
            for i in range(NUM_WORKERS)
        ]
        await asyncio.gather(*workers)

    print("✅ Парсинг завершён.")


if __name__ == "__main__":
    asyncio.run(main())