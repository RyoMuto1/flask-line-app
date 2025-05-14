import os
import sqlite3
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

# .env をロード
load_dotenv()

def create_admin(email, password):
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # パスワードをハッシュ化
    hashed_password = generate_password_hash(password)
    
    try:
        c.execute('INSERT INTO admins (email, password) VALUES (?, ?)',
                 (email, hashed_password))
        conn.commit()
        print(f"管理者アカウントを作成しました: {email}")
    except sqlite3.IntegrityError:
        print(f"このメールアドレスは既に登録されています: {email}")
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")
    finally:
        conn.close()

if __name__ == '__main__':
    email = input("管理者のメールアドレスを入力してください: ")
    password = input("パスワードを入力してください: ")
    create_admin(email, password) 