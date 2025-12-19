# safe_page_parser_fixed.py
import requests
import time
import random
import os
from bs4 import BeautifulSoup

# === Настройки ===
BASE_URL = "https://www.newsvl.ru/"
OUTPUT_FILE = "collected_links.txt"
START_PAGE = 1
END_PAGE = 3020

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 YaBrowser/25.6.1.1000 Yowser/2.5 Safari/537.36",
]

DELAY_RANGE = (3.0, 7.0)

def extract_news_links_from_page(html):
    """Извлекает ТОЛЬКО ссылки из <h3 class="story-list__item-title"><a href="...">"""
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    for h3 in soup.find_all('h3', class_='story-list__item-title'):
        a = h3.find('a', href=True)
        if a:
            href = a['href'].strip()
            if href.startswith('/'):
                href = BASE_URL.rstrip('/') + href
            links.append(href)
    return links

def load_existing_links():
    """Загружает существующие ссылки из файла (если он есть)"""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    else:
        # Создаём пустой файл, если его нет
        open(OUTPUT_FILE, 'w', encoding='utf-8').close()
        return set()

def save_links(links):
    """Перезаписывает файл всеми уникальными ссылками"""
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for link in sorted(links):
            f.write(link + '\n')

def main():
    all_links = load_existing_links()
    print(f"📥 Загружено {len(all_links)} ранее собранных ссылок")

    for page in range(START_PAGE, END_PAGE + 1):
        print(f"\n📄 Страница {page} из {END_PAGE}")
        url = f"{BASE_URL}?page={page}"

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                links = extract_news_links_from_page(resp.text)
                new_links = [link for link in links if link not in all_links]
                all_links.update(links)
                print(f"   ➕ Найдено {len(links)} ссылок ({len(new_links)} новых)")
            else:
                print(f"   ⚠️ HTTP {resp.status_code}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    print("   💤 Пауза на 10 секунд из-за ошибки...")
                    time.sleep(10)

        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            print("   💤 Пауза на 15 секунд...")
            time.sleep(15)

        # Сохраняем после каждой страницы
        save_links(all_links)

        # Человеческая задержка
        delay = random.uniform(*DELAY_RANGE)
        print(f"   ⏳ Пауза: {delay:.1f} сек...")
        time.sleep(delay)

    print(f"\n✅ Всего собрано: {len(all_links)} уникальных ссылок")

if __name__ == "__main__":
    main()