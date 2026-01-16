import sqlite3

SOURCE_DB = "lenta2.db"   # откуда берем новые записи
TARGET_DB = "lenta.db"    # куда добавляем

def merge_databases():
    # Подключаемся к целевой базе (lenta.db)
    target_conn = sqlite3.connect(TARGET_DB)
    target_cur = target_conn.cursor()

    # Подключаемся к источнику (lenta2.db)
    source_conn = sqlite3.connect(SOURCE_DB)
    source_cur = source_conn.cursor()

    # Получаем все записи из lenta2.db
    source_cur.execute("SELECT guid, title, description, url, published_at, comments_count, created_at_utc, rating FROM articles")
    rows = source_cur.fetchall()

    print(f"📥 Найдено {len(rows)} записей в {SOURCE_DB}")

    # Вставляем в lenta.db с игнорированием дублей по url
    inserted = 0
    for row in rows:
        try:
            target_cur.execute("""
                INSERT OR IGNORE INTO articles
                (guid, title, description, url, published_at, comments_count, created_at_utc, rating)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
            if target_cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"❌ Ошибка при вставке {row[3]}: {e}")

    target_conn.commit()
    print(f"✅ Успешно добавлено {inserted} новых записей в {TARGET_DB}")

    # Закрываем соединения
    source_conn.close()
    target_conn.close()

if __name__ == "__main__":
    merge_databases()