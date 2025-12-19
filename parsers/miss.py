from pathlib import Path
import sqlite3

# === Конфигурация ===
DB_PATH = "lenta.db"
DONE_FILE = Path("done_lenta.txt")
OUTPUT_FILE = "missing_in_db.txt"

def main():
    # 1. Считываем URL из БД
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT url FROM articles")
    db_urls = set(row[0] for row in cur.fetchall())
    conn.close()
    print(f"✅ Загружено {len(db_urls)} URL из базы данных")

    # 2. Считываем URL из done_lenta.txt
    if not DONE_FILE.exists():
        print(f"❌ Файл {DONE_FILE} не найден")
        return

    with open(DONE_FILE, encoding="utf-8") as f:
        done_urls = set(line.strip() for line in f if line.strip())
    print(f"✅ Загружено {len(done_urls)} URL из {DONE_FILE}")

    # 3. Находим разницу: обработано, но не в БД
    missing = done_urls - db_urls

    print(f"\n🔍 Найдено {len(missing)} ссылок, которые есть в done_lenta.txt, но отсутствуют в БД")

    if missing:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            for url in sorted(missing):
                f.write(url + "\n")
        print(f"📄 Список сохранён в {OUTPUT_FILE}")
    else:
        print("🎉 Все обработанные ссылки успешно сохранены в БД")

if __name__ == "__main__":
    main()