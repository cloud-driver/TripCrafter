import sqlite3

def init_db():
    conn = sqlite3.connect('test_database.db')  # 用測試檔名避免衝突
    cursor = conn.cursor()
    
    sql = '''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            active_id TEXT NOT NULL,
            schedule TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    '''
    try:
        cursor.execute(sql)
        conn.commit()
        print("資料庫初始化成功！")
    except sqlite3.OperationalError as e:
        print("錯誤：", e)
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
