import asyncio
import random
import os
from pathlib import Path
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

# === Конфигурация ===
BASE_URL = "https://www.newsvl.ru/"
OUTPUT_FILE = Path("raw_vl_links.txt")
START_PAGE = 2664
END_PAGE = 3090
NUM_WORKERS = 3
DELAY_RANGE = (1.0, 2.0)  # на каждый запрос

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 YaBrowser/25.6.1.1000 Yowser/2.5 Safari/537.36",
]

# Глобальное множество (потокобезопасно в asyncio, так как один поток)
collected_links = set()
collected_links_lock = asyncio.Lock()

# === Загрузка существующих ссылок ===
def load_existing_links():
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    else:
        OUTPUT_FILE.write_text("")
        return set()

# === Сохранение ===
def save_links(links):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for link in sorted(links):
            f.write(link + "\n")

# === Извлечение ссылок ===
def extract_news_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for h3 in soup.find_all("h3", class_="story-list__item-title"):
        a = h3.find("a", href=True)
        if a:
            full_url = urljoin(BASE_URL, a["href"].strip())
            links.append(full_url)
    return links

# === Воркер ===
async def worker(worker_id: int, page_queue: asyncio.Queue, client: httpx.AsyncClient):
    while not page_queue.empty():
        page = await page_queue.get()
        url = f"{BASE_URL}?page={page}"

        headers = {"User-Agent": random.choice(USER_AGENTS)}
        try:
            resp = await client.get(url, headers=headers, timeout=15.0)

            if resp.status_code == 200:
                new_links = extract_news_links(resp.text)
                async with collected_links_lock:
                    before = len(collected_links)
                    collected_links.update(new_links)
                    added = len(collected_links) - before
                    print(f"[{worker_id}] Страница {page}: +{len(new_links)} ссылок ({added} новых)")
                    save_links(collected_links)
            else:
                print(f"[{worker_id}] Страница {page}: HTTP {resp.status_code}")
                if resp.status_code in (429, 500, 502, 503):
                    await asyncio.sleep(10)

        except Exception as e:
            print(f"[{worker_id}] Ошибка на странице {page}: {e}")
            await asyncio.sleep(10)

        # Задержка между запросами — критически важна
        delay = random.uniform(*DELAY_RANGE)
        await asyncio.sleep(delay)

        page_queue.task_done()

# === Главная функция ===
async def main():
    global collected_links
    collected_links = load_existing_links()
    print(f"📥 Загружено {len(collected_links)} ранее собранных ссылок")

    # Очередь страниц
    page_queue = asyncio.Queue()
    for page in range(START_PAGE, END_PAGE + 1):
        page_queue.put_nowait(page)

    # Запуск воркеров
    async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
        workers = [
            asyncio.create_task(worker(i + 1, page_queue, client))
            for i in range(NUM_WORKERS)
        ]
        await asyncio.gather(*workers)

    print(f"\n✅ Всего собрано: {len(collected_links)} уникальных ссылок")

if __name__ == "__main__":
    asyncio.run(main())