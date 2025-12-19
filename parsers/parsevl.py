import asyncio
import random
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import sqlite3
from urllib.parse import urlparse

# === Конфигурация ===
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

URLS_FILE = "article_links.txt"
DONE_FILE = Path("done.txt")
DEAD_FILE = Path("dead_links.txt")
DB_PATH = "news.db"
REQUEST_TIMEOUT = 15

client: httpx.AsyncClient


# === Извлечение даты из URL для сортировки ===
def extract_date_for_sort(url: str):
    """Извлекает (год, месяц, день) из URL вида /2021/10/28/ для сортировки. Возвращает кортеж или (0,0,0) при ошибке."""
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 5:
            year = int(parts[-5])
            month = int(parts[-4])
            day = int(parts[-3])
            if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return (year, month, day)
    except (ValueError, IndexError):
        pass
    return (0, 0, 0)  # ссылки без даты — в конец


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
    for tag in soup.select("img, video, audio, iframe, figure, script, style"):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# === Парсинг статьи ===
def parse_article(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    # Обязательные блоки: заголовок и текст
    title_tag = soup.select_one("h1.story__title")
    text_container = soup.select_one("div.story__text")

    if not title_tag or not text_container:
        print(f"  → Пропущено: отсутствует заголовок или текст-контейнер на {url}")
        return None

    title = title_tag.get_text(strip=True)
    if not title:
        print(f"  → Пропущено: пустой заголовок на {url}")
        return None

    # Очистка текста
    description = clean_text(str(text_container))
    if not description:
        print(f"  → Пропущено: текст статьи пуст после очистки на {url}")
        return None

    # Парсинг даты
    published_at = None
    date_tag = soup.select_one("span.story__info-date")
    if date_tag:
        date_str = date_tag.get_text(strip=True)
        ru_months = {
            "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
            "мая": "05", "июня": "06", "июля": "07", "августа": "08",
            "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"
        }
        for ru, num in ru_months.items():
            date_str = date_str.replace(ru, num)
        try:
            dt = datetime.strptime(date_str, "%H:%M, %d %m %Y")
            published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass  # остаётся None

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
                # Не добавляем в done.txt — но и не обрабатываем
                url_queue.task_done()
                continue

            if resp.status_code != 200:
                print(f"[{worker_id}] HTTP {resp.status_code} — {url}")
                url_queue.task_done()
                continue

            article = parse_article(resp.text, url)
            if article:
                save_article(article)
                print(f"[{worker_id}] Сохранено: {article['title'][:60]}...")
            else:
                print(f"[{worker_id}] Пропущено (пусто): {url}")

            with open(DONE_FILE, "a", encoding="utf-8") as f:
                f.write(url + "\n")

        except Exception as e:
            print(f"[{worker_id}] Ошибка на {url}: {e}")

        delay = random.uniform(0.8, 1.5)
        await asyncio.sleep(delay)
        url_queue.task_done()


# === Главная функция ===
async def main():
    global client
    init_db()

    # Загрузка всех ссылок
    with open(URLS_FILE, encoding="utf-8") as f:
        raw_urls = [line.strip() for line in f if line.strip()]

    # Уникальность + сортировка по дате из URL
    unique_urls = list(dict.fromkeys(raw_urls))  # сохраняем порядок, убираем дубли
    print(f"Всего уникальных ссылок: {len(unique_urls)}")

    # Сортируем: сначала по дате из URL, затем остальные
    sorted_urls = sorted(unique_urls, key=extract_date_for_sort)

    # Загрузка прогресса
    done = set()
    if DONE_FILE.exists():
        with open(DONE_FILE, encoding="utf-8") as f:
            done = set(line.strip() for line in f)

    dead = set()
    if DEAD_FILE.exists():
        with open(DEAD_FILE, encoding="utf-8") as f:
            dead = set(line.strip() for line in f)

    # Фильтрация: только не обработанные и не мёртвые
    to_process = [url for url in sorted_urls if url not in done and url not in dead]

    if not to_process:
        print("Нет ссылок для обработки.")
        return

    print(f"К обработке: {len(to_process)} статей (из {len(sorted_urls)})")

    # Очередь
    url_queue = asyncio.Queue()
    for url in to_process:
        url_queue.put_nowait(url)

    # Запуск
    async with httpx.AsyncClient(http2=True, timeout=REQUEST_TIMEOUT) as client:
        workers = [
            asyncio.create_task(worker(1, url_queue)),
            asyncio.create_task(worker(2, url_queue)),
        ]
        await asyncio.gather(*workers)

    print("✅ Парсинг завершён.")


if __name__ == "__main__":
    asyncio.run(main())