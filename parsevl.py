import os
import time
import random
import uuid
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

# === Настройки ===
SITEMAP_URL = "https://www.newsvl.ru/sitemap_vl_news.xml"
DB_FILE = "news.db"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 YaBrowser/25.6.1.1000 Yowser/2.5 Safari/537.36",
]

REQUEST_DELAY = (0.5, 1.0)  # Уменьшено для скорости, но безопасно


# === 1. Создаём базу данных ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            guid TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            published_at TEXT,
            comments_count INTEGER,
            created_at_utc TEXT NOT NULL,
            rating INTEGER
        )
    """)
    conn.commit()
    conn.close()


# === 2. Получаем URL из sitemap ===
def fetch_sitemap_urls():
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    resp = requests.get(SITEMAP_URL, headers=headers, timeout=10)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    urls = []
    for url_tag in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
        url = url_tag.text.strip()
        urls.append(url)
    print(f"📥 Найдено {len(urls)} статей в sitemap.")
    return urls


# === 3. Очищаем текст статьи — только содержимое story__text ===
def clean_article_text(soup):
    # Ищем основной блок текста
    text_block = soup.find("div", class_="story__text")
    if not text_block:
        return None

    # Удаляем медиа и ненужные теги
    for tag in text_block.select("img, video, audio, iframe, script, style, figure, .embed-responsive"):
        tag.decompose()

    # Убираем ссылки, но сохраняем их текст
    for a in text_block.find_all("a"):
        a.unwrap()

    # Получаем чистый текст с переносами
    text = text_block.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines) if lines else None


# === 4. Парсим одну статью ===
def parse_article(url):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        print(f"⚠️ Ошибка {resp.status_code} при загрузке {url}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    # Заголовок — h1 с классом story__title
    title_elem = soup.find("h1", class_="story__title")
    title = title_elem.get_text(strip=True) if title_elem else "Без заголовка"

    # Текст — из div.story__text
    description = clean_article_text(soup)
    if not description:
        return None  # Пропускаем, если нет текста

    # Дата публикации — из URL: /2025/04/18/
    published_at = None
    import re
    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if match:
        year, month, day = match.groups()
        published_at = f"{year}-{month}-{day} 00:00:00"

    return {
        "guid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "url": url,
        "published_at": published_at,
        "comments_count": 0,      # на сайте нет комментариев → 0
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "rating": None            # рейтинга нет → NULL
    }


# === 5. Сохраняем в БД ===
def save_article(article):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO articles
            (guid, title, description, url, published_at, comments_count, created_at_utc, rating)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(article.values()))
        conn.commit()
        print(f"✅ Сохранено: {article['title'][:60]}...")
    except sqlite3.IntegrityError:
        print(f"🔁 Уже есть: {article['url']}")
    finally:
        conn.close()


# === 6. Основной запуск ===
def main():
    init_db()
    urls = fetch_sitemap_urls()

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] Парсинг: {url}")
        article = parse_article(url)
        if article:
            save_article(article)
        time.sleep(random.uniform(*REQUEST_DELAY))

    print("🎉 Готово! Все статьи сохранены в news.db")


if __name__ == "__main__":
    main()