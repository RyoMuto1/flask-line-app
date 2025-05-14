import os
import sqlite3
import logging

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
    logger.info(f"データベースパス: {db_path}")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 管理者テーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admins'")
    if not c.fetchone():
        logger.info("adminsテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("adminsテーブルを作成しました")

    # 注文テーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    if not c.fetchone():
        logger.info("ordersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                item TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                event_date TEXT,
                class_teacher TEXT,
                school_name TEXT,
                delivery_name TEXT,
                postal_code TEXT,
                prefecture TEXT,
                city TEXT,
                address TEXT,
                budget TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("ordersテーブルを作成しました")

    conn.close()
    logger.info("データベースの初期化が完了しました")

if __name__ == '__main__':
    init_db() 