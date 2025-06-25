import os
import sqlite3
import requests
import jwt    # ← 追加
from flask import (
    Flask, render_template, request,
    redirect, jsonify, session, Response, flash, url_for
)
from dotenv import load_dotenv
import logging  # 追加
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from functools import wraps  # 追加
import urllib.parse  # URLエンコーディング用に追加
from flask_socketio import SocketIO  # 追加
from werkzeug.utils import secure_filename
from datetime import datetime
import re # 正規表現モジュール
import uuid

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# .env をロード
load_dotenv()

app = Flask(__name__)
# セッション用の鍵
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
# Socket.IO の初期化
socketio = SocketIO(app, cors_allowed_origins="*")

# --- 設定値 ---
DATABASE = 'database.db'
UPLOAD_FOLDER_TEMPLATES = 'static/uploads/templates' # テンプレート画像保存フォルダ
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}     # 許可する拡張子

app.config['UPLOAD_FOLDER_TEMPLATES'] = UPLOAD_FOLDER_TEMPLATES

# --- ユーティリティ関数 ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 新しいメッセージが届いたときに全クライアントに通知
def notify_new_message(user_id, message, is_from_admin=False):
    socketio.emit('new_message', {
        'user_id': user_id,
        'message': message,
        'is_from_admin': is_from_admin
    })

# 管理者認証用デコレータ
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return decorated_function

# DB 初期化
def init_db():
    # Renderの永続ディスクがある場合はそこにDBを保存、ない場合は従来のパス
    if os.path.exists('/opt/render'):
        # Renderの永続ディスクパス（Render管理画面で設定した値）
        PERSISTENT_DISK_DIR = '/opt/render/project/.render-data'
        
        # ディレクトリの存在確認と作成
        if not os.path.exists(PERSISTENT_DISK_DIR):
            try:
                os.makedirs(PERSISTENT_DISK_DIR, exist_ok=True)
                logger.info(f"永続ディレクトリを作成しました: {PERSISTENT_DISK_DIR}")
            except Exception as e:
                logger.warning(f"永続ディレクトリの作成に失敗: {str(e)}")
                # 失敗した場合はプロジェクトディレクトリを使用
                PERSISTENT_DISK_DIR = '/opt/render/project/src/data'
                os.makedirs(PERSISTENT_DISK_DIR, exist_ok=True)
        else:
            logger.info(f"既存の永続ディレクトリを使用: {PERSISTENT_DISK_DIR}")
            
        db_path = os.path.join(PERSISTENT_DISK_DIR, 'orders.db')
        logger.info(f"データベースパス: {db_path}")
    else:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
        logger.info(f"ローカルディスクを使用します: {db_path}")
    
    logger.info(f"データベースパス: {db_path}")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 流入元分析フォルダテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='source_analytics_folders'")
    if not c.fetchone():
        logger.info("source_analytics_foldersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE source_analytics_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # デフォルトの「未分類」フォルダを作成
        c.execute('''
            INSERT INTO source_analytics_folders (name, sort_order, created_at)
            VALUES ('未分類', 0, datetime('now'))
        ''')
        
        conn.commit()
        logger.info("source_analytics_foldersテーブルを作成し、デフォルトフォルダを追加しました")
    else:
        # テーブルが存在する場合、「未分類」フォルダがあるかチェック
        c.execute("SELECT COUNT(*) FROM source_analytics_folders WHERE name = '未分類'")
        uncategorized_count = c.fetchone()[0]
        
        if uncategorized_count == 0:
            logger.info("「未分類」フォルダが存在しないため、追加します")
            # 最大のsort_orderを取得
            c.execute('SELECT MAX(sort_order) FROM source_analytics_folders')
            max_order = c.fetchone()[0] or -1
            
            c.execute('''
                INSERT INTO source_analytics_folders (name, sort_order, created_at)
                VALUES ('未分類', ?, datetime('now'))
            ''', (max_order + 1,))
            
            # 既存のfolder_idがNULLの登録リンクを「未分類」フォルダに移動
            c.execute("SELECT id FROM source_analytics_folders WHERE name = '未分類' ORDER BY id DESC LIMIT 1")
            uncategorized_id = c.fetchone()[0]
            
            c.execute('UPDATE registration_links SET folder_id = ? WHERE folder_id IS NULL', (uncategorized_id,))
            
            conn.commit()
            logger.info("「未分類」フォルダを追加し、既存リンクを移動しました")

    # 登録リンク管理テーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='registration_links'")
    if not c.fetchone():
        logger.info("registration_linksテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE registration_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,           -- リンクの名前（例：Instagram用）
                source TEXT NOT NULL,         -- 流入元（例：instagram）
                link_code TEXT UNIQUE NOT NULL, -- 一意のリンクコード
                folder_id INTEGER,            -- フォルダID（NULL可）
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES source_analytics_folders(id)
            )
        ''')
        conn.commit()
        logger.info("registration_linksテーブルを作成しました")
    else:
        # 既存のテーブルにfolder_id列を追加
        c.execute("PRAGMA table_info(registration_links)")
        columns = [row[1] for row in c.fetchall()]
        if 'folder_id' not in columns:
            logger.info("registration_linksテーブルにfolder_id列を追加します")
            c.execute("ALTER TABLE registration_links ADD COLUMN folder_id INTEGER REFERENCES source_analytics_folders(id)")
            conn.commit()
            logger.info("registration_linksテーブルにfolder_id列を追加しました")

    # ユーザー登録経路テーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_registrations'")
    if not c.fetchone():
        logger.info("user_registrationsテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE user_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT NOT NULL,
                registration_link_id INTEGER NOT NULL,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (registration_link_id) REFERENCES registration_links(id),
                UNIQUE(line_user_id, registration_link_id)
            )
        ''')
        conn.commit()
        logger.info("user_registrationsテーブルを作成しました")
    else:
        # テーブルの構造を修正（既存のユニーク制約を変更）
        try:
            logger.info("user_registrationsテーブルの構造を修正します")
            c.execute("PRAGMA foreign_keys=off")
            c.execute("BEGIN TRANSACTION")
            
            # 一時テーブルを作成
            c.execute('''
                CREATE TABLE user_registrations_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT NOT NULL,
                    registration_link_id INTEGER NOT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (registration_link_id) REFERENCES registration_links(id),
                    UNIQUE(line_user_id, registration_link_id)
                )
            ''')
            
            # データを移行（重複があれば最初のレコードのみ）
            c.execute('''
                INSERT OR IGNORE INTO user_registrations_new(id, line_user_id, registration_link_id, registered_at)
                SELECT id, line_user_id, registration_link_id, registered_at FROM user_registrations
            ''')
            
            # 元のテーブルを削除して新しいテーブルをリネーム
            c.execute("DROP TABLE user_registrations")
            c.execute("ALTER TABLE user_registrations_new RENAME TO user_registrations")
            
            c.execute("COMMIT")
            c.execute("PRAGMA foreign_keys=on")
            logger.info("user_registrationsテーブルの構造を修正しました")
        except Exception as e:
            logger.error(f"テーブル構造の修正に失敗しました: {str(e)}")
            c.execute("ROLLBACK")
            c.execute("PRAGMA foreign_keys=on")

    # ユーザーテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not c.fetchone():
        logger.info("usersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT,
                profile_image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("usersテーブルを作成しました")
    else:
        # email列をusersテーブルに追加（なければ）
        c.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in c.fetchall()]
        if 'email' not in columns:
            logger.info("usersテーブルにemail列を追加します")
            c.execute("ALTER TABLE users ADD COLUMN email TEXT")
            conn.commit()
            logger.info("usersテーブルにemail列を追加しました")
        # profile_image_url列をusersテーブルに追加（なければ）
        if 'profile_image_url' not in columns:
            logger.info("usersテーブルにprofile_image_url列を追加します")
            c.execute("ALTER TABLE users ADD COLUMN profile_image_url TEXT")
            conn.commit()
            logger.info("usersテーブルにprofile_image_url列を追加しました")

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
        
        # デフォルト管理者アカウントを自動作成
        try:
            default_email = "admin@example.com"
            default_password = "adminpassword"
            hashed_password = generate_password_hash(default_password)
            
            c.execute('''
                INSERT INTO admins (email, password, created_at)
                VALUES (?, ?, datetime('now'))
            ''', (default_email, hashed_password))
            conn.commit()
            logger.info(f"デフォルト管理者アカウントを作成しました: {default_email} / {default_password}")
            logger.info("このアカウントは初期設定用です。ログイン後、必ずパスワードを変更してください。")
        except Exception as e:
            logger.error(f"デフォルト管理者アカウント作成エラー: {str(e)}")

    # チャットルームテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_rooms'")
    if not c.fetchone():
        logger.info("chat_roomsテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE chat_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("chat_roomsテーブルを作成しました")

    # チャット参加者テーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_participants'")
    if not c.fetchone():
        logger.info("chat_participantsテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE chat_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                line_user_id TEXT NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id),
                UNIQUE(room_id, line_user_id)
            )
        ''')
        conn.commit()
        logger.info("chat_participantsテーブルを作成しました")

    # チャットメッセージテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'")
    if not c.fetchone():
        logger.info("chat_messagesテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                sender_id TEXT NOT NULL,
                message TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id)
            )
        ''')
        conn.commit()
        logger.info("chat_messagesテーブルを作成しました")

    # 管理者・ユーザー間のチャットメッセージテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_chat_messages'")
    if not c.fetchone():
        logger.info("admin_chat_messagesテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE admin_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                line_user_id TEXT NOT NULL,
                message TEXT NOT NULL,
                is_from_admin BOOLEAN NOT NULL,
                read_status BOOLEAN DEFAULT 0,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(id)
            )
        ''')
        conn.commit()
        logger.info("admin_chat_messagesテーブルを作成しました")
    
    # ユーザーメモテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'")
    if not c.fetchone():
        logger.info("user_notesテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE user_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT NOT NULL,
                admin_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES admins(id),
                UNIQUE(line_user_id, admin_id)
            )
        ''')
        conn.commit()
        logger.info("user_notesテーブルを作成しました")

    # テーブルが存在するか確認
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    if not c.fetchone():
        logger.info("ordersテーブルが存在しないため、新規作成します")
        # フルスキーマでテーブル作成
        c.execute('''
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                name_kana TEXT NOT NULL,
                phone TEXT NOT NULL,
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
    else:
        # マイグレーション：必要なカラムを追加
        existing = [row[1] for row in c.execute("PRAGMA table_info(orders)").fetchall()]
        additions = [
            ("event_date",   "TEXT"),
            ("class_teacher","TEXT"),
            ("school_name",  "TEXT"),
            ("delivery_name","TEXT"),
            ("postal_code",  "TEXT"),
            ("prefecture",   "TEXT"),
            ("city",         "TEXT"),
            ("address",      "TEXT"),
            ("budget",       "TEXT"),
            ("name_kana",    "TEXT"),
            ("phone",        "TEXT")
        ]
        for name, col_type in additions:
            if name not in existing:
                logger.info(f"カラム '{name}' が存在しないため追加します")
                c.execute(f"ALTER TABLE orders ADD COLUMN {name} {col_type}")
        conn.commit()
        logger.info("ordersテーブルのマイグレーションが完了しました")

    # タグフォルダテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tag_folders'")
    if not c.fetchone():
        logger.info("tag_foldersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE tag_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT DEFAULT '#FFA500',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("tag_foldersテーブルを作成しました")
        
        # デフォルトの「未分類」フォルダを作成
        c.execute('''
            INSERT INTO tag_folders (name, sort_order, created_at)
            VALUES ('未分類', 0, datetime('now'))
        ''')
        conn.commit()
        logger.info("「未分類」フォルダを作成しました")

    # 新しいタグテーブル構造への移行チェック
    c.execute("PRAGMA table_info(tags)")
    columns = [row[1] for row in c.fetchall()]
    
    if 'folder_id' not in columns and 'parent_id' in columns:
        logger.info("タグテーブルを新構造に移行します")
        
        # 新構造のテーブルを作成
        c.execute('''
            CREATE TABLE tags_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES tag_folders(id)
            )
        ''')
        
        # 未分類フォルダのIDを取得
        c.execute("SELECT id FROM tag_folders WHERE name = '未分類' LIMIT 1")
        uncategorized_folder_id = c.fetchone()[0]
        
        # 既存のタグを未分類フォルダに移行（簡単な移行）
        c.execute("SELECT id, name, created_at FROM tags WHERE parent_id IS NULL")
        existing_tags = c.fetchall()
        
        for tag in existing_tags:
            c.execute('''
                INSERT INTO tags_new (folder_id, name, created_at)
                VALUES (?, ?, ?)
            ''', (uncategorized_folder_id, tag[1], tag[2]))
        
        # 古いテーブルをリネーム
        c.execute("ALTER TABLE tags RENAME TO tags_old")
        c.execute("ALTER TABLE tags_new RENAME TO tags")
        
        conn.commit()
        logger.info("タグテーブルの新構造への移行が完了しました")
    elif 'folder_id' not in columns:
        logger.info("新しいtagsテーブル構造を作成します")
        c.execute("DROP TABLE IF EXISTS tags")
        c.execute('''
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES tag_folders(id)
            )
        ''')
        conn.commit()
        logger.info("新しいtagsテーブル構造を作成しました")

    # ユーザーとタグの紐付けテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_tags'")
    if not c.fetchone():
        logger.info("user_tagsテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE user_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (line_user_id) REFERENCES users(line_user_id),
                FOREIGN KEY (tag_id) REFERENCES tags(id),
                UNIQUE(line_user_id, tag_id)
            )
        ''')
        conn.commit()
        logger.info("user_tagsテーブルを作成しました")

    # 対応マークテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='status_markers'")
    if not c.fetchone():
        logger.info("status_markersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE status_markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#808080',
                order_index INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("status_markersテーブルを作成しました")

    # ユーザーと対応マークの関連テーブル
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_status_markers'")
    if not c.fetchone():
        logger.info("user_status_markersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE user_status_markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                line_user_id TEXT NOT NULL,
                marker_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (line_user_id) REFERENCES users(line_user_id),
                FOREIGN KEY (marker_id) REFERENCES status_markers(id),
                UNIQUE(line_user_id, marker_id)
            )
        ''')
        conn.commit()
        logger.info("user_status_markersテーブルを作成しました")

    # テンプレートフォルダテーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='template_folders'")
    if not c.fetchone():
        logger.info("template_foldersテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE template_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT DEFAULT '#FFA500',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("template_foldersテーブルを作成しました")

    # message_templatesテーブルの存在確認と作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_templates'")
    if not c.fetchone():
        logger.info("message_templatesテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE message_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'text',  -- 'text', 'image', 'video', 'carousel', 'flex'
                content TEXT NOT NULL,              -- メッセージ内容またはJSON
                preview_text TEXT,                  -- プレビュー用テキスト
                image_url TEXT,                     -- 画像URL（画像タイプの場合）
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES template_folders(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
        logger.info("message_templatesテーブルを作成しました")
    else:
        # 既存テーブルにimage_urlカラムが存在するかチェック
        c.execute("PRAGMA table_info(message_templates)")
        columns = [column[1] for column in c.fetchall()]
        if 'image_url' not in columns:
            logger.info("message_templatesテーブルにimage_urlカラムを追加します")
            c.execute('ALTER TABLE message_templates ADD COLUMN image_url TEXT')
            conn.commit()
            logger.info("image_urlカラムを追加しました")

    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    # Renderの永続ディスクがある場合はそこにDBを保存、ない場合は従来のパス
    if os.path.exists('/opt/render'):
        # Renderの永続ディスクパス（Render管理画面で設定した値）
        PERSISTENT_DISK_DIR = '/opt/render/project/.render-data'
        
        # ディレクトリの存在確認
        if not os.path.exists(PERSISTENT_DISK_DIR):
            logger.warning(f"永続ディレクトリが存在しません: {PERSISTENT_DISK_DIR}")
            # 代替パスを使用
            PERSISTENT_DISK_DIR = '/opt/render/project/src/data'
            os.makedirs(PERSISTENT_DISK_DIR, exist_ok=True)
            logger.info(f"代替ディレクトリを使用: {PERSISTENT_DISK_DIR}")
        
        db_path = os.path.join(PERSISTENT_DISK_DIR, 'orders.db')
        logger.info(f"データベースパス: {db_path}")
    else:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
        logger.info(f"ローカルディスクを使用します: {db_path}")
    
    logger.info(f"データベースに接続します: {db_path}")

    if not os.path.exists(db_path):
        logger.warning(f"データベースファイルが存在しません: {db_path}")
        return init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # テーブル存在チェック
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    if not c.fetchone():
        logger.warning("ordersテーブルが存在しません。再初期化します。")
        conn.close()
        return init_db()

    return conn

# LINE Push helper
def send_line_message(user_id, message):
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    res = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={"to": user_id, "messages":[{"type":"text","text":message}]}
    )
    logger.debug(f"LINE Push → {res.status_code} {res.text}")
    return res.status_code == 200

def send_line_image_message(user_id, image_url):
    """LINE画像メッセージを送信する関数"""
    try:
        logger.info(f"画像メッセージ送信開始: user_id={user_id}, image_url={image_url}")
        
        # 画像URLの検証
        if not image_url:
            logger.error("画像URLが空です")
            return False
            
        # HTTPSに変換
        if image_url.startswith('http://'):
            image_url = image_url.replace('http://', 'https://')
            logger.info(f"HTTPSに変換: {image_url}")
        
        # URLの形式チェック
        if not (image_url.startswith('https://') or image_url.startswith('http://')):
            logger.error(f"無効なURL形式: {image_url}")
            return False
        
        token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
        
        # リクエストペイロードをログ出力
        payload = {
            "to": user_id, 
            "messages": [{
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url
            }]
        }
        logger.info(f"送信ペイロード: {payload}")
        
        res = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=payload
        )
        
        logger.info(f"LINE Image Push Response → Status: {res.status_code}")
        logger.info(f"LINE Image Push Response → Body: {res.text}")
        
        if res.status_code != 200:
            logger.error(f"LINE API Error: {res.status_code} - {res.text}")
            return False
            
        logger.info("画像メッセージ送信成功")
        return True
        
    except Exception as e:
        logger.error(f"画像メッセージ送信例外: {str(e)}")
        return False

# アプリケーションの初期化
with app.app_context():
    try:
        # データベースストレージのパスとパーミッションを確認
        if os.path.exists('/opt/render'):
            # Renderの永続ディスクパス
            PERSISTENT_DISK_DIR = '/opt/render/project/.render-data'
            logger.info(f"Render環境を検出: 永続ディスク {PERSISTENT_DISK_DIR}")
            
            # ディレクトリの存在確認
            if os.path.exists(PERSISTENT_DISK_DIR):
                logger.info(f"永続ディスクパスは存在します")
                # 書き込み権限の確認
                if os.access(PERSISTENT_DISK_DIR, os.W_OK):
                    logger.info(f"永続ディスクへの書き込み権限があります")
                else:
                    logger.warning(f"永続ディスクへの書き込み権限がありません！別の場所を使用します")
            else:
                logger.warning(f"永続ディスクパスが存在しません。作成を試みます")
        
        # データベース初期化（複数回実行しても安全）
        init_db()
        logger.info("データベースの初期化が完了しました")
        
        # 追加で「未分類」フォルダの存在確認と作成
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM source_analytics_folders WHERE name = '未分類'")
            uncategorized_count = c.fetchone()[0]
            
            if uncategorized_count == 0:
                logger.info("起動時チェック: 「未分類」フォルダが存在しないため、追加します")
                c.execute('SELECT MAX(sort_order) FROM source_analytics_folders')
                max_order = c.fetchone()[0] or -1
                
                c.execute('''
                    INSERT INTO source_analytics_folders (name, sort_order, created_at)
                    VALUES ('未分類', ?, datetime('now'))
                ''', (max_order + 1,))
                
                conn.commit()
                logger.info("起動時チェック: 「未分類」フォルダを追加しました")
            else:
                logger.info("起動時チェック: 「未分類」フォルダは既に存在します")
            
            conn.close()
        except Exception as folder_error:
            logger.error(f"「未分類」フォルダチェックエラー: {str(folder_error)}")
        
    except Exception as e:
        logger.error(f"データベース初期化エラー: {str(e)}")
        # エラーがあっても続行する
        pass

@app.route('/', methods=['GET', 'POST'])
def order_form():
    try:
        if not session.get('line_user_id'):
            return redirect('/login')

        if request.method == 'POST':
            required_fields = ['name', 'name_kana', 'phone', 'product_name', 'quantity', 'event_date', 
                             'class_teacher', 'school_name', 'delivery_name', 
                             'postal_code', 'prefecture', 'city', 'address', 'budget']
            for field in required_fields:
                if not request.form.get(field):
                    logger.error(f"必須フィールドが不足: {field}")
                    return f"必須項目が入力されていません: {field}", 400

            form_data = {
                'name': request.form.get('name'),
                'name_kana': request.form.get('name_kana'),
                'phone': request.form.get('phone'),
                'item': request.form.get('product_name'),
                'quantity': request.form.get('quantity'),
                'line_user_id': session['line_user_id']
            }
            logger.info(f"フォームデータ: {form_data}")

            try:
                conn = get_db()
                c = conn.cursor()
                c.execute('''
                    INSERT INTO orders (
                        line_user_id, name, name_kana, phone, item, quantity,
                        event_date, class_teacher, school_name,
                        delivery_name, postal_code, prefecture,
                        city, address, budget
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (
                    form_data['line_user_id'],
                    form_data['name'],
                    form_data['name_kana'],
                    form_data['phone'],
                    form_data['item'],
                    form_data['quantity'],
                    request.form.get('event_date'),
                    request.form.get('class_teacher'),
                    request.form.get('school_name'),
                    request.form.get('delivery_name'),
                    request.form.get('postal_code'),
                    request.form.get('prefecture'),
                    request.form.get('city'),
                    request.form.get('address'),
                    request.form.get('budget')
                ))
                conn.commit()
                conn.close()
                logger.info("データベースへの保存が完了しました")
            except Exception as db_error:
                logger.error(f"データベースエラー: {str(db_error)}")
                return f"データベースエラーが発生しました: {str(db_error)}", 500

            try:
                message = f'''\
{form_data["name"]}さん、ご注文ありがとうございます！

【注文内容】
商品名：{form_data["item"]}
数量：{form_data["quantity"]}枚
イベント日：{request.form.get('event_date')}
クラス・担任：{request.form.get('class_teacher')}

【お届け先】
学校名：{request.form.get('school_name')}
宛名：{request.form.get('delivery_name')}
郵便番号：{request.form.get('postal_code')}
住所：{request.form.get('prefecture')}{request.form.get('city')}{request.form.get('address')}

ご注文ありがとうございました！😊
'''
                send_line_message(
                    user_id=session['line_user_id'],
                    message=message
                )
                logger.info("LINE通知の送信が完了しました")
            except Exception as line_error:
                logger.error(f"LINE通知エラー: {str(line_error)}")
            return redirect('/thanks')

        return render_template('form.html')
    except Exception as e:
        logger.error(f"フォーム処理エラー: {str(e)}")
        return "エラーが発生しました。しばらく経ってから再度お試しください。", 500

@app.route('/thanks')
def thanks():
    return render_template('thanks.html')

@app.route('/history')
def history():
    conn = get_db()
    c    = conn.cursor()
    c.execute('SELECT name,item,quantity FROM orders')
    rows = c.fetchall()
    conn.close()

    html = '<h2>注文履歴</h2><ul>'
    for name,item,qty in rows:
        html += f'<li>{name} さん → {item} x {qty}</li>'
    html += '</ul>'
    return html

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.debug("📬 webhook hit：%s", request.get_data())
    
    try:
        # LINEからのイベントを処理
        signature = request.headers.get('X-Line-Signature', '')
        body = request.get_data(as_text=True)
        
        import json
        try:
            events = json.loads(body).get('events', [])
            
            for event in events:
                event_type = event.get('type')
                user_id = event.get('source', {}).get('userId')
                
                if user_id:
                    # ユーザープロフィールを更新（非同期にするのが理想的ですが、簡略化のため同期処理）
                    update_user_profile(user_id)
                
                # メッセージイベントを処理
                if event_type == 'message':
                    message_type = event.get('message', {}).get('type')
                    
                    # テキストメッセージを処理
                    if message_type == 'text':
                        message_text = event.get('message', {}).get('text')
                        
                        if user_id and message_text:
                            # ユーザーからのメッセージを管理者チャットに保存
                            conn = get_db()
                            cursor = conn.cursor()
                            
                            cursor.execute('''
                                INSERT INTO admin_chat_messages 
                                (line_user_id, message, is_from_admin, read_status, sent_at)
                                VALUES (?, ?, 0, 0, datetime('now'))
                            ''', (user_id, message_text))
                            
                            conn.commit()
                            conn.close()
                            
                            # WebSocketを通じて管理画面に通知
                            notify_new_message(user_id, message_text, is_from_admin=False)
        except Exception as e:
            logger.error(f"Webhookイベント処理エラー: {str(e)}")
    except Exception as e:
        logger.error(f"Webhook処理エラー: {str(e)}")
    
    return jsonify({"status":"ok"})

# LINE Login 設定
LINE_LOGIN_CHANNEL_ID     = os.environ["LINE_LOGIN_CHANNEL_ID"]
LINE_LOGIN_CHANNEL_SECRET = os.environ["LINE_LOGIN_CHANNEL_SECRET"]

if os.environ.get('FLASK_ENV') == 'development':
    LINE_REDIRECT_URI = 'http://localhost:10000/callback'
else:
    LINE_REDIRECT_URI = os.environ["LINE_REDIRECT_URI"]

@app.route('/login')
def login():
    source = request.args.get('source')
    logger.info(f"ログインルートにアクセス - source={source}, args={request.args}")
    
    if source:
        # セッションに流入元を保存（デコード済みの値を使用）
        try:
            # URLデコードが必要な場合にデコードする
            if '%' in source:
                source = urllib.parse.unquote(source)
            session['registration_source'] = source
            logger.info(f"流入元をセッションに保存: registration_source={source}")
        except Exception as e:
            logger.error(f"流入元の処理でエラー: {str(e)}")
    else:
        logger.info("流入元情報なしでログイン")
        
    return redirect('/line-login')

@app.route('/line-login')
def line_login():
    # LINE認証URLを生成
    state = secrets.token_urlsafe(16)
    session['line_login_state'] = state
    
    # 常にHTTPSで固定のコールバックURLを使用する
    callback_url = "https://flask-line-app-essd.onrender.com/callback"
    logger.info(f"LINE認証用コールバックURL: {callback_url}")
    
    auth_params = {
        'response_type': 'code',
        'client_id': LINE_LOGIN_CHANNEL_ID,
        'redirect_uri': callback_url,
        'state': state,
        'scope': 'profile openid',  # openidスコープを追加
    }
    auth_url = 'https://access.line.me/oauth2/v2.1/authorize?' + '&'.join([f'{k}={v}' for k, v in auth_params.items()])
    return redirect(auth_url)

@app.route('/callback')
def callback():
    # リクエスト情報をデバッグ出力
    logger.info(f"コールバックルートにアクセス - args={request.args}")
    code = request.args.get('code')
    state = request.args.get('state')  # stateパラメータも取得
    
    # セッションのstateと比較して検証（セキュリティ対策）
    session_state = session.get('line_login_state')
    if not session_state or session_state != state:
        logger.warning(f"state不一致: session={session_state}, request={state}")
    
    # 常にHTTPSで固定のコールバックURLを使用する
    callback_url = "https://flask-line-app-essd.onrender.com/callback"
    logger.info(f"コールバックURLを使用: {callback_url}")
    
    try:
        token_res = requests.post(
            'https://api.line.me/oauth2/v2.1/token',
            headers={'Content-Type':'application/x-www-form-urlencoded'},
            data={
                'grant_type':'authorization_code',
                'code':code,
                'redirect_uri':callback_url,  # 実際のリダイレクト先URLを使用
                'client_id':LINE_LOGIN_CHANNEL_ID,
                'client_secret':LINE_LOGIN_CHANNEL_SECRET
            }
        )
        token_data = token_res.json()
        logger.info(f"トークンレスポンス: {token_data}")
        
        id_token = token_data.get('id_token')
        if not id_token:
            error_msg = token_data.get('error_description', 'id_token が取れませんでした')
            logger.error(f"ID Token取得エラー: {error_msg}")
            return Response(f"認証エラー: {error_msg}", status=500)

        try:
            payload = jwt.decode(id_token, options={"verify_signature": False})
        except Exception as e:
            logger.error("JWT decode error: %s", e)
            return Response("ID トークンの解析に失敗しました", status=500)

        user_id   = payload.get('sub')
        user_name = payload.get('name', '（名前なし）')
        if not user_id:
            return Response("ユーザーID(sub) が取得できませんでした", status=500)

        session['line_user_id']   = user_id
        session['line_user_name'] = user_name

        # ユーザープロフィールを更新（画像URLなどを取得）
        update_user_profile(user_id)

        # ユーザー情報を保存
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # ユーザー情報を保存（既存の場合はスキップ）
            try:
                cursor.execute('''
                    INSERT INTO users (line_user_id, name, created_at)
                    VALUES (?, ?, datetime('now'))
                ''', (user_id, user_name))
                logger.info(f"新規ユーザーを登録しました: {user_name}")
            except sqlite3.IntegrityError:
                logger.info(f"既存ユーザーのログイン: {user_name}")
            
            # 流入元が指定されている場合は記録
            if 'registration_source' in session:
                source_code = session['registration_source']
                logger.info(f"登録リンク情報: source_code={source_code}")
                
                # 流入元リンクの存在を確認
                cursor.execute('SELECT * FROM registration_links WHERE link_code = ?', (source_code,))
                link = cursor.fetchone()
                
                if link:
                    link_id = link['id']
                    logger.info(f"リンク情報: id={link_id}, name={link['name']}")
                    
                    # 既に同じリンクからの登録があるか確認
                    cursor.execute('''
                        SELECT id FROM user_registrations 
                        WHERE line_user_id = ? AND registration_link_id = ?
                    ''', (user_id, link_id))
                    
                    if not cursor.fetchone():
                        # 新規登録
                        try:
                            cursor.execute('''
                                INSERT INTO user_registrations (line_user_id, registration_link_id, registered_at)
                                VALUES (?, ?, datetime('now'))
                            ''', (user_id, link_id))
                            logger.info(f"流入元 '{link['name']}' からのユーザー登録を記録しました")
                        except Exception as e:
                            logger.error(f"ユーザー登録エラー: {str(e)}")
                    else:
                        logger.info(f"すでに同じリンクからの登録があります: {link['name']}")
                else:
                    logger.warning(f"リンクコード '{source_code}' が見つかりません")
                
                # セッションから流入元を削除
                session.pop('registration_source', None)
            
            conn.commit()
        except Exception as e:
            logger.error(f"ユーザー情報保存エラー: {str(e)}")
        finally:
            conn.close()

        # LINE公式アカウントのトーク画面にリダイレクトする
        LINE_BOT_BASIC_ID = os.environ.get("LINE_BOT_BASIC_ID", "")
        if LINE_BOT_BASIC_ID:
            # 公式アカウントIDがある場合は、トーク画面に飛ばす
            line_talk_url = f"https://line.me/R/oaMessage/{LINE_BOT_BASIC_ID}"
            logger.info(f"LINEトーク画面にリダイレクト: {line_talk_url}")
            return redirect(line_talk_url)
        else:
            # 公式アカウントIDがない場合は通常どおりTOPにリダイレクト
            logger.warning("LINE_BOT_BASIC_IDが設定されていないため、TOPにリダイレクトします")
            return redirect('/')
            
    except Exception as e:
        logger.error(f"LINE認証エラー: {str(e)}")
        return Response(f"エラーが発生しました: {str(e)}", status=500)

@app.route('/mypage')
def mypage():
    try:
        if 'line_user_id' not in session:
            return redirect('/login')
        conn = get_db()
        c = conn.cursor()
        
        # ユーザー情報を取得（メールアドレスを含む）
        c.execute('SELECT * FROM users WHERE line_user_id = ?', (session['line_user_id'],))
        user = c.fetchone()
        user_dict = dict(user) if user else {'name': session.get('line_user_name', 'ゲスト'), 'email': ''}
        
        # 注文情報を取得
        c.execute('''
            SELECT name, item, quantity, event_date, class_teacher,
                   school_name, delivery_name, postal_code,
                   prefecture, city, address, created_at
              FROM orders
             WHERE line_user_id = ?
             ORDER BY created_at DESC
        ''', (session['line_user_id'],))
        orders = [dict(zip([column[0] for column in c.description], row)) for row in c.fetchall()]
        conn.close()
        
        return render_template('mypage.html', 
                               user=user_dict,
                               orders=orders)
    except Exception as e:
        logger.error(f"マイページエラー: {str(e)}")
        return "エラーが発生しました。しばらく経ってから再度お試しください。", 500

@app.route('/update-email', methods=['POST'])
def update_email():
    if 'line_user_id' not in session:
        return redirect('/login')
    
    email = request.form.get('email')
    if not email:
        flash('メールアドレスを入力してください', 'error')
        return redirect('/mypage')
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # ユーザー情報を更新
        c.execute('UPDATE users SET email = ? WHERE line_user_id = ?', 
                 (email, session['line_user_id']))
        conn.commit()
        conn.close()
        
        flash('メールアドレスを更新しました', 'success')
    except Exception as e:
        logger.error(f"メールアドレス更新エラー: {str(e)}")
        flash('エラーが発生しました。もう一度お試しください', 'error')
    
    return redirect('/mypage')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM admins WHERE email = ?', (email,))
        admin = c.fetchone()
        conn.close()
        
        if admin and check_password_hash(admin['password'], password):
            session['admin_id'] = admin['id']
            session['admin_email'] = admin['email']
            return redirect('/admin/dashboard')
        
        flash('メールアドレスまたはパスワードが正しくありません。', 'error')
        return render_template('admin/login.html')
    
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect('/admin/login')
    
    conn = get_db()
    c = conn.cursor()
    # LINEユーザー名を含めて注文を取得
    c.execute('''
        SELECT o.id, o.name, o.school_name, o.event_date, o.budget, o.created_at, 
               o.line_user_id, u.name as line_name
        FROM orders o
        LEFT JOIN users u ON o.line_user_id = u.line_user_id
        ORDER BY o.created_at DESC
    ''')
    orders = [dict(zip([column[0] for column in c.description], row)) for row in c.fetchall()]
    conn.close()
    
    return render_template('admin/dashboard.html', orders=orders)

@app.route('/admin/order/<int:order_id>')
def admin_order_detail(order_id):
    if 'admin_id' not in session:
        return redirect('/admin/login')
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT *
        FROM orders
        WHERE id = ?
    ''', (order_id,))
    order = dict(zip([column[0] for column in c.description], c.fetchone()))
    conn.close()
    
    return render_template('admin/order_detail.html', order=order)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    return redirect('/admin/login')

# LINE流入経路分析ページ
@app.route('/admin/line-source-analytics')
@admin_required
def line_source_analytics():
    conn = get_db()
    cursor = conn.cursor()
    
    # フォルダ一覧を取得（リンク数も含める）
    cursor.execute('''
        SELECT saf.*, COUNT(rl.id) as link_count
        FROM source_analytics_folders saf
        LEFT JOIN registration_links rl ON saf.id = rl.folder_id
        GROUP BY saf.id
        ORDER BY saf.sort_order, saf.name
    ''')
    folders = cursor.fetchall()
    
    # フォルダが存在しない場合は「未分類」フォルダを作成
    if not folders:
        logger.info("フォルダが存在しないため、「未分類」フォルダを作成します")
        cursor.execute('''
            INSERT INTO source_analytics_folders (name, sort_order, created_at)
            VALUES ('未分類', 0, datetime('now'))
        ''')
        conn.commit()
        
        # 再度フォルダ一覧を取得
        cursor.execute('SELECT * FROM source_analytics_folders ORDER BY sort_order, name')
        folders = cursor.fetchall()
        logger.info("「未分類」フォルダを作成しました")
    
    # 選択されたフォルダIDを取得（デフォルトは「未分類」フォルダ）
    selected_folder_id = request.args.get('folder_id', type=int)
    if not selected_folder_id and folders:
        # デフォルトは最初のフォルダ（未分類）を選択
        selected_folder_id = folders[0]['id']
    
    # sort_orderカラムの存在確認と追加
    cursor.execute("PRAGMA table_info(registration_links)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'sort_order' not in columns:
        cursor.execute('ALTER TABLE registration_links ADD COLUMN sort_order INTEGER DEFAULT 0')
        conn.commit()
        logger.info("registration_linksテーブルにsort_orderカラムを追加しました")

    # 登録リンク一覧を取得（登録者数も含める、ソート順適用）
    if selected_folder_id:
        cursor.execute('''
            SELECT rl.*, COUNT(ur.id) as registration_count, saf.name as folder_name
            FROM registration_links rl
            LEFT JOIN user_registrations ur ON rl.id = ur.registration_link_id
            LEFT JOIN source_analytics_folders saf ON rl.folder_id = saf.id
            WHERE rl.folder_id = ? OR (rl.folder_id IS NULL AND ? = (SELECT id FROM source_analytics_folders WHERE name = '未分類' LIMIT 1))
            GROUP BY rl.id
            ORDER BY COALESCE(rl.sort_order, 999), rl.created_at DESC
        ''', (selected_folder_id, selected_folder_id))
    else:
        cursor.execute('''
            SELECT rl.*, COUNT(ur.id) as registration_count, saf.name as folder_name
            FROM registration_links rl
            LEFT JOIN user_registrations ur ON rl.id = ur.registration_link_id
            LEFT JOIN source_analytics_folders saf ON rl.folder_id = saf.id
            GROUP BY rl.id
            ORDER BY COALESCE(rl.sort_order, 999), rl.created_at DESC
        ''')
    links = cursor.fetchall()
    
    # リンクの完全なURLを生成（SQLite3.Rowはイミュータブルなので辞書に変換）
    result_links = []
    for link in links:
        link_dict = dict(link)
        
        # 環境に応じたURLを構築
        if os.path.exists('/opt/render'):
            # Render環境では絶対URLを使用
            base_url = "https://flask-line-app-essd.onrender.com"
        else:
            # ローカル環境ではリクエストベースのURLを使用
            base_url = request.host_url.rstrip('/')
        
        # 完全なURLを構築（URLエンコード処理を追加）
        encoded_link_code = urllib.parse.quote(link['link_code'])
        link_dict['full_url'] = f"{base_url}/login?source={encoded_link_code}"
        logger.info(f"流入リンク生成: {link_dict['full_url']}")
        
        result_links.append(link_dict)
    
    conn.close()
    return render_template('admin/line_source_analytics.html', 
                         registration_links=result_links, 
                         folders=folders, 
                         selected_folder_id=selected_folder_id)

# 新しい登録リンクの作成
@app.route('/admin/line-source-analytics/create-link', methods=['POST'])
@admin_required
def create_registration_link():
    try:
        name = request.form.get('name')
        source = request.form.get('source')
        folder_id = request.form.get('folder_id')
        
        if not name or not source:
            return jsonify({'success': False, 'message': 'リンク名と流入元は必須です'}), 400
        
        # フォルダIDが空文字列の場合は「未分類」フォルダのIDを取得
        if folder_id == '':
            # 「未分類」フォルダのIDを取得
            conn_temp = get_db()
            cursor_temp = conn_temp.cursor()
            cursor_temp.execute("SELECT id FROM source_analytics_folders WHERE name = '未分類' LIMIT 1")
            uncategorized_folder = cursor_temp.fetchone()
            folder_id = uncategorized_folder['id'] if uncategorized_folder else None
            conn_temp.close()
        elif folder_id:
            folder_id = int(folder_id)
        
        # ユニークなリンクコードを生成
        link_code = secrets.token_urlsafe(8)
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO registration_links (name, source, link_code, folder_id, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            ''', (name, source, link_code, folder_id))
            conn.commit()
            return jsonify({'success': True, 'message': '登録リンクを作成しました'})
        except sqlite3.IntegrityError as e:
            logger.error(f"データベースエラー: {str(e)}")
            return jsonify({'success': False, 'message': 'リンクコードの生成に失敗しました。もう一度お試しください'}), 500
        finally:
            conn.close()
        
    except Exception as e:
        logger.error(f"登録リンク作成エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'エラーが発生しました。もう一度お試しください'}), 500

# 登録者一覧ページ
@app.route('/admin/line-source-analytics/users/<int:link_id>')
@admin_required
def line_source_analytics_users(link_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # 登録リンクの情報を取得
    cursor.execute('SELECT * FROM registration_links WHERE id = ?', (link_id,))
    link_row = cursor.fetchone()
    
    if not link_row:
        flash('指定された登録リンクが見つかりません', 'error')
        return redirect(url_for('line_source_analytics'))
    
    # SQLite3.Rowを辞書に変換
    link = dict(link_row)
    
    # このリンクから登録したユーザー一覧を取得
    cursor.execute('''
        SELECT 
            u.line_user_id,
            u.name,
            ur.registered_at,
            COUNT(o.id) as order_count
        FROM user_registrations ur
        JOIN users u ON ur.line_user_id = u.line_user_id
        LEFT JOIN orders o ON u.line_user_id = o.line_user_id
        WHERE ur.registration_link_id = ?
        GROUP BY u.line_user_id
        ORDER BY ur.registered_at DESC
    ''', (link_id,))
    user_rows = cursor.fetchall()
    
    # SQLite3.Rowのリストを辞書のリストに変換
    users = [dict(user) for user in user_rows]
    
    conn.close()
    return render_template('admin/line_source_analytics_users.html', link=link, users=users)

@app.route('/admin/change_password', methods=['GET', 'POST'])
@admin_required
def admin_change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # 現在のパスワードを確認
        conn = get_db()
        admin = conn.execute('SELECT * FROM admins WHERE id = ?', (session['admin_id'],)).fetchone()
        conn.close()
        
        if not check_password_hash(admin['password'], current_password):
            flash('現在のパスワードが正しくありません。', 'error')
            return redirect(url_for('admin_change_password'))
        
        # 新しいパスワードの確認
        if new_password != confirm_password:
            flash('新しいパスワードが一致しません。', 'error')
            return redirect(url_for('admin_change_password'))
        
        # パスワードの更新
        conn = get_db()
        conn.execute('UPDATE admins SET password = ? WHERE id = ?',
                    (generate_password_hash(new_password), session['admin_id']))
        conn.commit()
        conn.close()
        
        flash('パスワードを更新しました。', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('admin/change_password.html')

@app.route('/admin/reset-password', methods=['GET', 'POST'])
def admin_reset_password():
    if request.method == 'POST':
        email = request.form.get('email')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not email or not new_password or not confirm_password:
            flash('すべての項目を入力してください。', 'error')
            return render_template('admin/reset_password.html')
        
        if new_password != confirm_password:
            flash('新しいパスワードが一致しません。', 'error')
            return render_template('admin/reset_password.html')
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM admins WHERE email = ?', (email,))
        admin = c.fetchone()
        
        if not admin:
            flash('このメールアドレスは登録されていません。', 'error')
            return render_template('admin/reset_password.html')
        
        # パスワードをリセット
        c.execute('UPDATE admins SET password = ? WHERE id = ?', 
                 (generate_password_hash(new_password), admin['id']))
        conn.commit()
        conn.close()
        
        flash('パスワードがリセットされました。新しいパスワードでログインしてください。', 'success')
        return redirect(url_for('admin_login'))
    
    return render_template('admin/reset_password.html')

@app.route('/admin/create-first-admin', methods=['GET', 'POST'])
def create_first_admin():
    try:
        # 既存の管理者アカウントがある場合はリダイレクト
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as count FROM admins')
        count = c.fetchone()['count']
        conn.close()
        
        if count > 0:
            flash('管理者アカウントは既に作成されています。', 'error')
            return redirect(url_for('admin_login'))
        
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
            
            if not email or not password or not confirm_password:
                flash('すべての項目を入力してください。', 'error')
                return render_template('admin/first_admin.html')
            
            if password != confirm_password:
                flash('パスワードが一致しません。', 'error')
                return render_template('admin/first_admin.html')
            
            # 管理者アカウントを作成
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute('INSERT INTO admins (email, password, created_at) VALUES (?, ?, datetime("now"))', 
                        (email, generate_password_hash(password)))
                conn.commit()
                conn.close()
                
                flash('管理者アカウントが作成されました。ログインしてください。', 'success')
                return redirect(url_for('admin_login'))
            except sqlite3.IntegrityError:
                conn.close()
                flash('このメールアドレスは既に使用されています。', 'error')
                return render_template('admin/first_admin.html')
            except Exception as e:
                logger.error(f"管理者アカウント作成エラー: {str(e)}")
                flash('エラーが発生しました。もう一度お試しください。', 'error')
                return render_template('admin/first_admin.html')
        
        return render_template('admin/first_admin.html')
    except Exception as e:
        logger.error(f"初回管理者登録エラー: {str(e)}")
        flash('エラーが発生しました。もう一度お試しください。', 'error')
        return render_template('admin/first_admin.html')

@app.route('/admin/profile', methods=['GET', 'POST'])
@admin_required
def admin_profile():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM admins WHERE id = ?', (session['admin_id'],))
    admin = c.fetchone()
    
    if request.method == 'POST':
        email = request.form.get('email')
        current_password = request.form.get('current_password')
        
        if not email or not current_password:
            flash('すべての項目を入力してください。', 'error')
            return render_template('admin/profile.html', admin=admin)
        
        # パスワードを確認
        if not check_password_hash(admin['password'], current_password):
            flash('現在のパスワードが正しくありません。', 'error')
            return render_template('admin/profile.html', admin=admin)
        
        # 他の管理者が同じメールアドレスを使用していないか確認
        c.execute('SELECT * FROM admins WHERE email = ? AND id != ?', (email, session['admin_id']))
        existing_admin = c.fetchone()
        if existing_admin:
            flash('このメールアドレスは既に使用されています。', 'error')
            return render_template('admin/profile.html', admin=admin)
        
        # メールアドレスを更新
        c.execute('UPDATE admins SET email = ? WHERE id = ?', (email, session['admin_id']))
        conn.commit()
        conn.close()
        
        # セッションも更新
        session['admin_email'] = email
        
        flash('プロフィールが更新されました。', 'success')
        return redirect(url_for('admin_dashboard'))
    
    conn.close()
    return render_template('admin/profile.html', admin=admin)

@app.route('/admin/admin-list')
@admin_required
def admin_list():
    # フラッシュメッセージをクリア（管理者一覧画面では不要なメッセージを表示しない）
    session.pop('_flashes', None)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM admins ORDER BY id')
    admins = c.fetchall()
    conn.close()
    
    return render_template('admin/admin_list.html', 
                           admins=admins, 
                           current_admin_id=session['admin_id'])

@app.route('/admin/delete-admin/<int:admin_id>', methods=['POST'])
@admin_required
def delete_admin(admin_id):
    # 自分自身は削除できないようにする
    if admin_id == session['admin_id']:
        flash('自分自身は削除できません。', 'error')
        return redirect(url_for('admin_list'))
    
    conn = get_db()
    c = conn.cursor()
    
    # 管理者アカウントの総数を確認
    c.execute('SELECT COUNT(*) as count FROM admins')
    count = c.fetchone()['count']
    
    # 最後の管理者は削除できないようにする
    if count <= 1:
        flash('最後の管理者アカウントは削除できません。', 'error')
        conn.close()
        return redirect(url_for('admin_list'))
    
    # 管理者を削除
    c.execute('DELETE FROM admins WHERE id = ?', (admin_id,))
    conn.commit()
    conn.close()
    
    flash('管理者アカウントを削除しました。', 'success')
    return redirect(url_for('admin_list'))

# フォルダ作成
@app.route('/admin/line-source-analytics/folders/create', methods=['POST'])
@admin_required
def create_source_analytics_folder():
    try:
        name = request.form.get('name')
        
        if not name:
            return jsonify({'success': False, 'message': 'フォルダ名は必須です'}), 400
        
        # 「未分類」フォルダ名は予約語として使用不可
        if name == '未分類':
            return jsonify({'success': False, 'message': '「未分類」は予約語のため使用できません'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 最大のsort_orderを取得
        cursor.execute('SELECT MAX(sort_order) FROM source_analytics_folders')
        max_order = cursor.fetchone()[0] or 0
        
        cursor.execute('''
            INSERT INTO source_analytics_folders (name, sort_order, created_at)
            VALUES (?, ?, datetime('now'))
        ''', (name, max_order + 1))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'フォルダを作成しました'})
    except Exception as e:
        logger.error(f"フォルダ作成エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'フォルダの作成に失敗しました'}), 500

# フォルダ編集
@app.route('/admin/line-source-analytics/folders/edit/<int:folder_id>', methods=['POST'])
@admin_required
def edit_source_analytics_folder(folder_id):
    try:
        name = request.form.get('name')
        
        if not name:
            flash('フォルダ名は必須です', 'error')
            return redirect(url_for('line_source_analytics'))
        
        # 「未分類」フォルダ名は予約語として使用不可
        if name == '未分類':
            flash('「未分類」は予約語のため使用できません', 'error')
            return redirect(url_for('line_source_analytics'))
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE source_analytics_folders SET name = ? WHERE id = ?', (name, folder_id))
        
        if cursor.rowcount == 0:
            flash('フォルダが見つかりません', 'error')
        else:
            conn.commit()
            flash('フォルダ名を更新しました', 'success')
        
        conn.close()
    except Exception as e:
        logger.error(f"フォルダ編集エラー: {str(e)}")
        flash('フォルダの編集に失敗しました', 'error')
    
    return redirect(url_for('line_source_analytics'))

# フォルダ削除
@app.route('/admin/line-source-analytics/folders/delete/<int:folder_id>', methods=['POST'])
@admin_required
def delete_source_analytics_folder(folder_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 「未分類」フォルダは削除できないようにする
        cursor.execute('SELECT name FROM source_analytics_folders WHERE id = ?', (folder_id,))
        folder = cursor.fetchone()
        if folder and folder['name'] == '未分類':
            flash('「未分類」フォルダは削除できません', 'error')
            conn.close()
            return redirect(url_for('line_source_analytics'))
        
        # 「未分類」フォルダのIDを取得
        cursor.execute("SELECT id FROM source_analytics_folders WHERE name = '未分類' LIMIT 1")
        uncategorized_folder = cursor.fetchone()
        uncategorized_id = uncategorized_folder['id'] if uncategorized_folder else None
        
        # フォルダ内のリンクを「未分類」フォルダに移動
        if uncategorized_id:
            cursor.execute('UPDATE registration_links SET folder_id = ? WHERE folder_id = ?', (uncategorized_id, folder_id))
        else:
            cursor.execute('UPDATE registration_links SET folder_id = NULL WHERE folder_id = ?', (folder_id,))
        
        # フォルダを削除
        cursor.execute('DELETE FROM source_analytics_folders WHERE id = ?', (folder_id,))
        
        if cursor.rowcount == 0:
            flash('フォルダが見つかりません', 'error')
        else:
            conn.commit()
            flash('フォルダを削除しました', 'success')
        
        conn.close()
    except Exception as e:
        logger.error(f"フォルダ削除エラー: {str(e)}")
        flash('フォルダの削除に失敗しました', 'error')
    
    return redirect(url_for('line_source_analytics'))

# フォルダ並び替え機能
@app.route('/admin/line-source-analytics/folders/reorder', methods=['POST'])
@admin_required
def reorder_source_analytics_folders():
    try:
        data = request.json
        folder_order = data.get('folder_order', [])
        
        if not folder_order:
            return jsonify({'success': False, 'error': '並び替え情報が不正です'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 各フォルダに順序情報を保存
        for i, folder_id in enumerate(folder_order):
            cursor.execute('UPDATE source_analytics_folders SET sort_order = ? WHERE id = ?', (i, folder_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"フォルダ並び替えエラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 登録リンク並び替え機能
@app.route('/admin/line-source-analytics/links/reorder', methods=['POST'])
@admin_required
def reorder_registration_links():
    try:
        data = request.json
        link_order = data.get('link_order', [])
        folder_id = data.get('folder_id')
        
        if not link_order:
            return jsonify({'success': False, 'error': '並び替え情報が不正です'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 既存のテーブルにsort_orderカラムがなければ追加
        cursor.execute("PRAGMA table_info(registration_links)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'sort_order' not in columns:
            cursor.execute('ALTER TABLE registration_links ADD COLUMN sort_order INTEGER DEFAULT 0')
            logger.info("registration_linksテーブルにsort_orderカラムを追加しました")
        
        # 各リンクに順序情報を保存
        for i, link_id in enumerate(link_order):
            cursor.execute('UPDATE registration_links SET sort_order = ? WHERE id = ?', (i, link_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"リンク並び替えエラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 流入リンク削除機能
@app.route('/admin/line-source-analytics/delete-link/<int:link_id>', methods=['POST'])
@admin_required
def delete_registration_link(link_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 削除前にリンク情報を取得
        cursor.execute('SELECT * FROM registration_links WHERE id = ?', (link_id,))
        link = cursor.fetchone()
        
        if not link:
            flash('指定されたリンクが見つかりません', 'error')
            return redirect(url_for('line_source_analytics'))
        
        # 関連する登録情報を削除（外部キー制約がある場合）
        cursor.execute('DELETE FROM user_registrations WHERE registration_link_id = ?', (link_id,))
        
        # リンク自体を削除
        cursor.execute('DELETE FROM registration_links WHERE id = ?', (link_id,))
        
        conn.commit()
        flash(f'流入リンク "{link["name"]}" を削除しました', 'success')
        
    except Exception as e:
        logger.error(f"流入リンク削除エラー: {str(e)}")
        flash('エラーが発生しました。もう一度お試しください', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('line_source_analytics'))

# ユーザー詳細ページ
@app.route('/admin/user/<line_user_id>')
@admin_required
def admin_user_detail(line_user_id):
    conn = get_db()
    c = conn.cursor()
    
    # ユーザー情報を取得
    c.execute('SELECT * FROM users WHERE line_user_id = ?', (line_user_id,))
    user_row = c.fetchone()
    
    if not user_row:
        flash('指定されたユーザーが見つかりません', 'error')
        return redirect(url_for('admin_dashboard'))
    
    user = dict(user_row)
    
    # ユーザーの注文履歴を取得
    c.execute('''
        SELECT *
        FROM orders
        WHERE line_user_id = ?
        ORDER BY created_at DESC
    ''', (line_user_id,))
    orders = [dict(zip([column[0] for column in c.description], row)) for row in c.fetchall()]
    
    # ユーザーの登録リンク情報を取得
    c.execute('''
        SELECT rl.name as link_name, rl.source, ur.registered_at
        FROM user_registrations ur
        JOIN registration_links rl ON ur.registration_link_id = rl.id
        WHERE ur.line_user_id = ?
        ORDER BY ur.registered_at DESC
    ''', (line_user_id,))
    registrations = [dict(zip([column[0] for column in c.description], row)) for row in c.fetchall()]
    
    conn.close()
    
    return render_template('admin/user_detail.html', 
                          user=user, 
                          orders=orders,
                          registrations=registrations)

# チャット機能のルート
@app.route('/chat')
def chat_home():
    if 'line_user_id' not in session:
        return redirect('/login')
    
    conn = get_db()
    c = conn.cursor()
    
    # 自分が参加しているチャットルームを取得
    c.execute('''
        SELECT cr.id, cr.created_at,
               (SELECT name FROM users WHERE line_user_id = cr.creator_id) as creator_name,
               (SELECT COUNT(*) FROM chat_participants WHERE room_id = cr.id) as participant_count,
               (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id) as message_count,
               (SELECT MAX(sent_at) FROM chat_messages WHERE room_id = cr.id) as last_activity
        FROM chat_rooms cr
        JOIN chat_participants cp ON cr.id = cp.room_id
        WHERE cp.line_user_id = ?
        ORDER BY last_activity DESC NULLS LAST, cr.created_at DESC
    ''', (session['line_user_id'],))
    
    # SQLite3.Rowのリストを辞書のリストに変換
    try:
        rooms = [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"チャットルーム取得エラー: {str(e)}")
        rooms = []
    
    conn.close()
    
    return render_template('chat/home.html', rooms=rooms)

@app.route('/chat/users')
def chat_users():
    if not session.get('line_user_id'):
        return redirect('/login')
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT u.line_user_id, u.name, u.email, u.profile_image_url,
                   sm.name as status_marker_name, sm.color as status_marker_color
            FROM users u
            LEFT JOIN user_status_markers usm ON u.line_user_id = usm.line_user_id
            LEFT JOIN status_markers sm ON usm.marker_id = sm.id
            WHERE u.line_user_id != ?
            ORDER BY u.name
        ''', (session['line_user_id'],))
        
        users = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return render_template('chat/users.html', users=users)
    except Exception as e:
        logger.error(f"チャットユーザー一覧エラー: {str(e)}")
        flash('エラーが発生しました', 'danger')
        return redirect('/chat')

@app.route('/chat/create/<target_user_id>')
def create_chat(target_user_id):
    if 'line_user_id' not in session:
        return redirect('/login')
    
    # 自分自身とのチャットは作成できないようにする
    if target_user_id == session['line_user_id']:
        flash('自分自身とチャットを作成することはできません', 'error')
        return redirect('/chat/users')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 既存の1:1チャットルームがあるか確認
        cursor.execute('''
            SELECT cr.id
            FROM chat_rooms cr
            JOIN chat_participants cp1 ON cr.id = cp1.room_id
            JOIN chat_participants cp2 ON cr.id = cp2.room_id
            WHERE cp1.line_user_id = ? AND cp2.line_user_id = ?
            GROUP BY cr.id
            HAVING COUNT(DISTINCT cp1.line_user_id) = 2
        ''', (session['line_user_id'], target_user_id))
        
        existing_room = cursor.fetchone()
        
        if existing_room:
            # 既存のルームがある場合はそこにリダイレクト
            room_id = existing_room[0]
            return redirect(f'/chat/room/{room_id}')
        
        # 新しいチャットルームを作成
        cursor.execute('''
            INSERT INTO chat_rooms (creator_id, created_at)
            VALUES (?, datetime('now'))
        ''', (session['line_user_id'],))
        
        room_id = cursor.lastrowid
        
        # 参加者を追加（自分と相手）
        cursor.execute('''
            INSERT INTO chat_participants (room_id, line_user_id, joined_at)
            VALUES (?, ?, datetime('now'))
        ''', (room_id, session['line_user_id']))
        
        cursor.execute('''
            INSERT INTO chat_participants (room_id, line_user_id, joined_at)
            VALUES (?, ?, datetime('now'))
        ''', (room_id, target_user_id))
        
        conn.commit()
        
        # 作成したチャットルームにリダイレクト
        return redirect(f'/chat/room/{room_id}')
        
    except Exception as e:
        logger.error(f"チャットルーム作成エラー: {str(e)}")
        conn.rollback()
        flash('チャットルームの作成に失敗しました', 'error')
        return redirect('/chat/users')
    finally:
        conn.close()

@app.route('/chat/room/<int:room_id>')
def chat_room(room_id):
    if 'line_user_id' not in session:
        return redirect('/login')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # ユーザーがこのルームに参加しているか確認
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM chat_participants
        WHERE room_id = ? AND line_user_id = ?
    ''', (room_id, session['line_user_id']))
    
    result = cursor.fetchone()
    if not result or result[0] == 0:
        flash('このチャットルームにアクセスする権限がありません', 'error')
        return redirect('/chat')
    
    # ルーム情報を取得
    cursor.execute('''
        SELECT cr.*, 
               (SELECT name FROM users WHERE line_user_id = cr.creator_id) as creator_name
        FROM chat_rooms cr
        WHERE cr.id = ?
    ''', (room_id,))
    
    room = dict(cursor.fetchone())
    
    # 参加者情報を取得
    cursor.execute('''
        SELECT cp.*, u.name
        FROM chat_participants cp
        JOIN users u ON cp.line_user_id = u.line_user_id
        WHERE cp.room_id = ?
        ORDER BY cp.joined_at
    ''', (room_id,))
    
    participants = [dict(row) for row in cursor.fetchall()]
    
    # メッセージ履歴を取得
    cursor.execute('''
        SELECT cm.*, u.name as sender_name
        FROM chat_messages cm
        JOIN users u ON cm.sender_id = u.line_user_id
        WHERE cm.room_id = ?
        ORDER BY cm.sent_at
    ''', (room_id,))
    
    messages = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template('chat/room.html', 
                          room=room, 
                          participants=participants, 
                          messages=messages,
                          current_user_id=session['line_user_id'])

@app.route('/chat/send/<int:room_id>', methods=['POST'])
def send_message(room_id):
    if 'line_user_id' not in session:
        return redirect('/login')
    
    message_text = request.form.get('message')
    if not message_text:
        flash('メッセージを入力してください', 'error')
        return redirect(f'/chat/room/{room_id}')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # ユーザーがこのルームに参加しているか確認
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM chat_participants
            WHERE room_id = ? AND line_user_id = ?
        ''', (room_id, session['line_user_id']))
        
        result = cursor.fetchone()
        if not result or result[0] == 0:
            flash('このチャットルームにメッセージを送信する権限がありません', 'error')
            return redirect('/chat')
        
        # メッセージを保存
        cursor.execute('''
            INSERT INTO chat_messages (room_id, sender_id, message, sent_at)
            VALUES (?, ?, ?, datetime('now'))
        ''', (room_id, session['line_user_id'], message_text))
        
        conn.commit()
        
        # 参加者にLINE通知を送信（自分以外）
        cursor.execute('''
            SELECT cp.line_user_id, u.name
            FROM chat_participants cp
            JOIN users u ON cp.line_user_id = u.line_user_id
            WHERE cp.room_id = ? AND cp.line_user_id != ?
        ''', (room_id, session['line_user_id']))
        
        participants = cursor.fetchall()
        
        # 送信者の名前を取得
        cursor.execute('SELECT name FROM users WHERE line_user_id = ?', (session['line_user_id'],))
        sender_name = cursor.fetchone()[0]
        
        # LINE通知を送信
        for participant_id, participant_name in participants:
            try:
                notification = f"[チャット] {sender_name}さんからメッセージがあります:\n{message_text[:50]}..."
                send_line_message(participant_id, notification)
            except Exception as e:
                logger.error(f"LINE通知エラー: {str(e)}")
        
    except Exception as e:
        logger.error(f"メッセージ送信エラー: {str(e)}")
        conn.rollback()
        flash('メッセージの送信に失敗しました', 'error')
    finally:
        conn.close()
    
    return redirect(f'/chat/room/{room_id}')

# 管理者用チャット機能
@app.route('/admin/chat')
@admin_required
def admin_chat():
    return render_template('admin/chat/index.html')

# APIエンドポイント: ユーザー一覧取得
@app.route('/admin/api/users')
@admin_required
def api_users():
    conn = get_db()
    cursor = conn.cursor()
    
    # ユーザー一覧を取得（未読メッセージ数と最新メッセージ、対応マークも取得）
    cursor.execute('''
        SELECT u.line_user_id, u.name, u.email, u.profile_image_url, u.created_at,
               (SELECT COUNT(*) FROM admin_chat_messages 
                WHERE line_user_id = u.line_user_id AND is_from_admin = 0 AND read_status = 0) AS unread_count,
               (SELECT message FROM admin_chat_messages 
                WHERE line_user_id = u.line_user_id 
                ORDER BY sent_at DESC LIMIT 1) AS last_message,
               sm.name as status_marker_name, sm.color as status_marker_color
        FROM users u
        LEFT JOIN user_status_markers usm ON u.line_user_id = usm.line_user_id
        LEFT JOIN status_markers sm ON usm.marker_id = sm.id
        ORDER BY unread_count DESC, 
                 (SELECT MAX(sent_at) FROM admin_chat_messages WHERE line_user_id = u.line_user_id) DESC NULLS LAST,
                 u.created_at DESC
    ''')
    
    users = []
    for row in cursor.fetchall():
        users.append({
            'line_user_id': row['line_user_id'],
            'name': row['name'],
            'email': row['email'],
            'profile_image_url': row['profile_image_url'],
            'created_at': row['created_at'],
            'unread_count': row['unread_count'],
            'last_message': row['last_message'],
            'status_marker_name': row['status_marker_name'],
            'status_marker_color': row['status_marker_color']
        })
    
    conn.close()
    return jsonify({'success': True, 'users': users})

# APIエンドポイント: ユーザー情報取得
@app.route('/admin/api/user/<line_user_id>')
@admin_required
def api_user_info(line_user_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # ユーザー情報を取得（対応マークも含む）
    cursor.execute('''
        SELECT u.*, COUNT(o.id) as order_count,
               sm.id as status_marker_id, sm.name as status_marker_name, sm.color as status_marker_color
        FROM users u
        LEFT JOIN orders o ON u.line_user_id = o.line_user_id
        LEFT JOIN user_status_markers usm ON u.line_user_id = usm.line_user_id
        LEFT JOIN status_markers sm ON usm.marker_id = sm.id
        WHERE u.line_user_id = ?
        GROUP BY u.line_user_id
    ''', (line_user_id,))
    
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return jsonify({'success': False, 'error': 'ユーザーが見つかりません'})
    
    user = {
        'line_user_id': user_row['line_user_id'],
        'name': user_row['name'],
        'email': user_row['email'],
        'profile_image_url': user_row['profile_image_url'],
        'created_at': user_row['created_at'],
        'order_count': user_row['order_count'],
        'status_marker_id': user_row['status_marker_id'],
        'status_marker_name': user_row['status_marker_name'],
        'status_marker_color': user_row['status_marker_color']
    }
    
    conn.close()
    return jsonify({'success': True, 'user': user})

# APIエンドポイント: チャット履歴取得
@app.route('/admin/api/chat/<line_user_id>')
@admin_required
def api_chat_history(line_user_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # ユーザー情報を取得（プロフィール画像URL用）
    cursor.execute('SELECT profile_image_url FROM users WHERE line_user_id = ?', (line_user_id,))
    user_row = cursor.fetchone()
    profile_image_url = user_row['profile_image_url'] if user_row else None
    
    # チャット履歴を取得
    cursor.execute('''
        SELECT *
        FROM admin_chat_messages
        WHERE line_user_id = ?
        ORDER BY sent_at
    ''', (line_user_id,))
    
    messages = []
    for row in cursor.fetchall():
        messages.append({
            'id': row['id'],
            'admin_id': row['admin_id'],
            'line_user_id': row['line_user_id'],
            'message': row['message'],
            'is_from_admin': bool(row['is_from_admin']),
            'sent_at': row['sent_at'],
            'profile_image_url': profile_image_url if not bool(row['is_from_admin']) else None
        })
    
    # 未読メッセージを既読に更新
    cursor.execute('''
        UPDATE admin_chat_messages
        SET read_status = 1
        WHERE line_user_id = ? AND is_from_admin = 0 AND read_status = 0
    ''', (line_user_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'messages': messages})

# APIエンドポイント: メッセージ送信
@app.route('/admin/api/send-message', methods=['POST'])
@admin_required
def api_send_message():
    data = request.json
    user_id = data.get('user_id')
    message = data.get('message')
    
    if not user_id or not message:
        return jsonify({'success': False, 'error': '必要なパラメータが不足しています'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # メッセージをデータベースに保存
        cursor.execute('''
            INSERT INTO admin_chat_messages (admin_id, line_user_id, message, is_from_admin, sent_at)
            VALUES (?, ?, ?, 1, datetime('now'))
        ''', (session['admin_id'], user_id, message))
        
        conn.commit()
        
        # LINE APIを使用してメッセージを送信
        try:
            send_line_message(user_id, message)
        except Exception as e:
            logger.error(f"LINE API送信エラー: {str(e)}")
            # LINE APIの送信に失敗しても処理は続行
        
        conn.close()
        
        # WebSocketを通じて他の管理画面にも通知
        notify_new_message(user_id, message, is_from_admin=True)
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"メッセージ送信エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

# APIエンドポイント: ユーザーメモ取得
@app.route('/admin/api/user-note/<line_user_id>')
@admin_required
def api_user_note(line_user_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # メモを取得
    cursor.execute('''
        SELECT *
        FROM user_notes
        WHERE line_user_id = ? AND admin_id = ?
    ''', (line_user_id, session['admin_id']))
    
    note_row = cursor.fetchone()
    conn.close()
    
    if note_row:
        return jsonify({'success': True, 'note': note_row['note']})
    else:
        return jsonify({'success': True, 'note': ''})

# APIエンドポイント: ユーザーメモ保存
@app.route('/admin/api/save-note', methods=['POST'])
@admin_required
def api_save_note():
    data = request.json
    user_id = data.get('user_id')
    note = data.get('note')
    
    if not user_id:
        return jsonify({'success': False, 'error': 'ユーザーIDが必要です'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 既存のメモがあるか確認
        cursor.execute('''
            SELECT id
            FROM user_notes
            WHERE line_user_id = ? AND admin_id = ?
        ''', (user_id, session['admin_id']))
        
        note_row = cursor.fetchone()
        
        if note_row:
            # 既存のメモを更新
            cursor.execute('''
                UPDATE user_notes
                SET note = ?, updated_at = datetime('now')
                WHERE id = ?
            ''', (note, note_row['id']))
        else:
            # 新規メモを作成
            cursor.execute('''
                INSERT INTO user_notes (line_user_id, admin_id, note, created_at, updated_at)
                VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ''', (user_id, session['admin_id'], note))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"メモ保存エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

# LINE ユーザープロフィール取得
def get_line_user_profile(user_id):
    try:
        # LINEのチャネルアクセストークンを使用
        token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
        
        # LINEユーザープロフィールエンドポイント
        url = f"https://api.line.me/v2/bot/profile/{user_id}"
        
        # リクエストヘッダー
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # プロフィール情報を取得
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            profile_data = response.json()
            logger.info(f"LINEユーザープロフィール取得成功: {profile_data.get('displayName')}")
            return profile_data
        else:
            logger.error(f"LINEユーザープロフィール取得エラー: {response.status_code} {response.text}")
            return None
    except Exception as e:
        logger.error(f"LINEユーザープロフィール取得中に例外発生: {str(e)}")
        return None

# LINE公式アカウント情報取得
def get_line_bot_info():
    try:
        # LINEのチャネルアクセストークンを使用
        token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
        
        # LINE Bot情報エンドポイント
        url = "https://api.line.me/v2/bot/info"
        
        # リクエストヘッダー
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Bot情報を取得
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            bot_data = response.json()
            logger.info(f"LINE Bot情報取得成功: {bot_data.get('displayName')}")
            return bot_data
        else:
            logger.error(f"LINE Bot情報取得エラー: {response.status_code} {response.text}")
            return None
    except Exception as e:
        logger.error(f"LINE Bot情報取得中に例外発生: {str(e)}")
        return None

# ユーザープロフィール情報の更新
def update_user_profile(user_id):
    try:
        profile_data = get_line_user_profile(user_id)
        if not profile_data:
            return False
        
        conn = get_db()
        cursor = conn.cursor()
        
        # ユーザー情報を更新
        cursor.execute('''
            UPDATE users
            SET name = ?, profile_image_url = ?
            WHERE line_user_id = ?
        ''', (
            profile_data.get('displayName', '名称不明'),
            profile_data.get('pictureUrl', None),
            user_id
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"ユーザープロフィール情報を更新しました: {user_id}")
        return True
    except Exception as e:
        logger.error(f"ユーザープロフィール更新エラー: {str(e)}")
        return False

# タグ管理画面
@app.route('/admin/tags')
@admin_required
def admin_tags():
    conn = get_db()
    c = conn.cursor()
    
    # フォルダ一覧を取得
    c.execute('''
        SELECT tf.*, COUNT(t.id) as tag_count
        FROM tag_folders tf
        LEFT JOIN tags t ON tf.id = t.folder_id
        GROUP BY tf.id
        ORDER BY tf.sort_order, tf.name
    ''')
    folders = [dict(row) for row in c.fetchall()]
    
    conn.close()
    return render_template('admin/tags.html', folders=folders)

# タグフォルダ作成API
@app.route('/admin/tags/folders/create', methods=['POST'])
@admin_required
def create_tag_folder():
    logger.info("=== タグフォルダ作成APIが呼ばれました ===")
    name = request.form.get('name')
    logger.info(f"受信したフォルダ名: {name}")
    
    if not name:
        return jsonify({'success': False, 'error': 'フォルダ名は必須です'}), 400
    
    # 「未分類」フォルダ名は予約語として使用不可
    if name == '未分類':
        return jsonify({'success': False, 'error': '「未分類」は予約語のため使用できません'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ名の重複確認
        c.execute('SELECT id FROM tag_folders WHERE name = ?', (name,))
        if c.fetchone():
            return jsonify({'success': False, 'error': 'そのフォルダ名は既に使用されています'}), 400
        
        # 最大の順序を取得
        c.execute('SELECT MAX(sort_order) FROM tag_folders')
        max_order = c.fetchone()[0] or 0
        
        # フォルダを作成
        c.execute('''
            INSERT INTO tag_folders (name, sort_order, created_at) 
            VALUES (?, ?, datetime("now"))
        ''', (name, max_order + 1))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"タグフォルダ作成エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# タグ新規作成API
@app.route('/admin/tags/create', methods=['POST'])
@admin_required
def create_tag():
    logger.info("=== タグ作成APIが呼ばれました ===")
    name = request.form.get('name')
    folder_id = request.form.get('folder_id')
    logger.info(f"受信したタグ名: {name}, folder_id: {folder_id}")
    
    if not name:
        return jsonify({'success': False, 'error': 'タグ名は必須です'}), 400
    
    if not folder_id:
        # フォルダが指定されていない場合は未分類フォルダを使用
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM tag_folders WHERE name = '未分類' LIMIT 1")
        uncategorized_folder = c.fetchone()
        folder_id = uncategorized_folder[0] if uncategorized_folder else 1
        conn.close()
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT INTO tags (folder_id, name, created_at) VALUES (?, ?, datetime("now"))', (folder_id, name))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/import', methods=['POST'])
@admin_required
def import_tags():
    if 'csv_file' not in request.files:
        return jsonify({'success': False, 'error': 'CSVファイルが必要です'}), 400
        
    file = request.files['csv_file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'ファイルが選択されていません'}), 400
        
    if not file.filename.endswith('.csv'):
        return jsonify({'success': False, 'error': 'CSVファイルのみアップロード可能です'}), 400
    
    try:
        # CSVファイルを読み込む
        csv_content = file.read().decode('utf-8')
        lines = csv_content.strip().split('\n')
        
        conn = get_db()
        c = conn.cursor()
        
        # 各行を処理
        success_count = 0
        for line in lines:
            parts = line.strip().split(',')
            if len(parts) == 0 or not parts[0].strip():
                continue
                
            name = parts[0].strip()
            parent_id = None
            
            # 親IDがある場合
            if len(parts) > 1 and parts[1].strip():
                parent_id = parts[1].strip()
                
            # タグを保存
            c.execute('INSERT INTO tags (name, parent_id, created_at) VALUES (?, ?, datetime("now"))', (name, parent_id))
            success_count += 1
            
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'{success_count}件のタグをインポートしました'})
    except Exception as e:
        logger.error(f"タグインポートエラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/edit/<int:tag_id>', methods=['POST'])
@admin_required
def edit_tag(tag_id):
    name = request.form.get('name')
    if not name:
        return jsonify({'success': False, 'error': 'タグ名は必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # タグが存在するか確認
        c.execute('SELECT id FROM tags WHERE id = ?', (tag_id,))
        tag = c.fetchone()
        if not tag:
            return jsonify({'success': False, 'error': 'タグが見つかりません'}), 404
        
        # タグ名を更新
        c.execute('UPDATE tags SET name = ? WHERE id = ?', (name, tag_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"タグ更新エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/delete/<int:tag_id>', methods=['POST'])
@admin_required
def delete_tag(tag_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # タグが存在するか確認
        c.execute('SELECT id FROM tags WHERE id = ?', (tag_id,))
        tag = c.fetchone()
        if not tag:
            return jsonify({'success': False, 'error': 'タグが見つかりません'}), 404
            
        # このタグを親とするタグがないか確認
        c.execute('SELECT COUNT(*) as count FROM tags WHERE parent_id = ?', (tag_id,))
        child_count = c.fetchone()['count']
        if child_count > 0:
            return jsonify({'success': False, 'error': 'このフォルダには子タグが含まれています。先に子タグを削除してください。'}), 400
        
        # 関連するuser_tagsを削除
        c.execute('DELETE FROM user_tags WHERE tag_id = ?', (tag_id,))
        
        # タグを削除
        c.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"タグ削除エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/delete-multiple', methods=['POST'])
@admin_required
def delete_multiple_tags():
    """タグ一括削除"""
    try:
        tag_ids = request.form.getlist('tag_ids')
        
        if not tag_ids:
            return jsonify({'success': False, 'error': '削除するタグを選択してください'})
        
        conn = get_db()
        c = conn.cursor()
        
        # タグに関連するユーザータグを削除
        placeholders = ','.join(['?' for _ in tag_ids])
        c.execute(f'DELETE FROM user_tags WHERE tag_id IN ({placeholders})', tag_ids)
        
        # タグを削除
        c.execute(f'DELETE FROM tags WHERE id IN ({placeholders})', tag_ids)
        
        deleted_count = c.rowcount
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'{deleted_count}個のタグが削除されました'})
        
    except Exception as e:
        logger.error(f"タグ一括削除エラー: {str(e)}")
        return jsonify({'success': False, 'error': 'タグの削除に失敗しました'})

@app.route('/admin/tags/users/<int:tag_id>')
@admin_required
def tag_users_api(tag_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # タグが存在するか確認
        c.execute('SELECT id FROM tags WHERE id = ?', (tag_id,))
        tag = c.fetchone()
        if not tag:
            return jsonify({'success': False, 'error': 'タグが見つかりません'}), 404
        
        # タグに紐づくユーザー一覧を取得
        c.execute('''
            SELECT u.line_user_id, u.name, u.email, u.profile_image_url, u.created_at
            FROM users u
            JOIN user_tags ut ON u.line_user_id = ut.line_user_id
            WHERE ut.tag_id = ?
            ORDER BY u.name
        ''', (tag_id,))
        
        users = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        logger.error(f"タグユーザー取得エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/remove-user', methods=['POST'])
@admin_required
def remove_tag_from_user():
    data = request.json
    user_id = data.get('user_id')
    tag_id = data.get('tag_id')
    
    if not user_id or not tag_id:
        return jsonify({'success': False, 'error': 'ユーザーIDとタグIDは必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # タグとユーザーの関連を削除
        c.execute('DELETE FROM user_tags WHERE line_user_id = ? AND tag_id = ?', (user_id, tag_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"タグ削除エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/reorder', methods=['POST'])
@admin_required
def reorder_tags():
    try:
        data = request.json
        folder_order = data.get('folder_order', [])
        
        if not folder_order:
            return jsonify({'success': False, 'error': '並び替え情報が不正です'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # 既存のフォルダにorder_indexカラムがなければ追加
        c.execute("PRAGMA table_info(tags)")
        columns = [row[1] for row in c.fetchall()]
        if 'order_index' not in columns:
            c.execute('ALTER TABLE tags ADD COLUMN order_index INTEGER')
            logger.info("tagsテーブルにorder_indexカラムを追加しました")
        
        # 各フォルダに順序情報を保存
        for i, folder_id in enumerate(folder_order):
            c.execute('UPDATE tags SET order_index = ? WHERE id = ?', (i, folder_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"フォルダ並び替えエラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/tags/folders/delete/<int:folder_id>', methods=['POST'])
@admin_required
def delete_tag_folder(folder_id):
    """タグフォルダ削除"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ存在確認
        c.execute('SELECT id, name FROM tags WHERE id = ? AND parent_id IS NULL', (folder_id,))
        folder = c.fetchone()
        if not folder:
            return jsonify({'success': False, 'message': 'フォルダが見つかりません'})
        
        # 「未分類」フォルダは削除不可
        if folder['name'] == '未分類':
            return jsonify({'success': False, 'message': '「未分類」フォルダは削除できません'})
        
        # フォルダ内のタグ数を確認
        c.execute('SELECT COUNT(*) as count FROM tags WHERE parent_id = ?', (folder_id,))
        tag_count = c.fetchone()[0]
        
        if tag_count > 0:
            return jsonify({'success': False, 'message': f'このフォルダには{tag_count}個のタグが含まれています。先にタグを削除または移動してください。'})
        
        # フォルダ削除
        c.execute('DELETE FROM tags WHERE id = ?', (folder_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'フォルダが削除されました'})
        
    except Exception as e:
        logger.error(f"タグフォルダ削除エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'フォルダの削除に失敗しました'})

@app.route('/admin/tags/folders/edit/<int:folder_id>', methods=['POST'])
@admin_required
def edit_tag_folder(folder_id):
    """タグフォルダ編集"""
    try:
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#FFA500').strip()
        
        if not name:
            return jsonify({'success': False, 'message': 'フォルダ名は必須です'})
        
        # 「未分類」フォルダ名は予約語として使用不可
        if name == '未分類':
            return jsonify({'success': False, 'message': '「未分類」は予約語のため使用できません'})
        
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ存在確認
        c.execute('SELECT id FROM tags WHERE id = ? AND parent_id IS NULL', (folder_id,))
        if not c.fetchone():
            return jsonify({'success': False, 'message': 'フォルダが見つかりません'})
        
        # フォルダ名の重複確認
        c.execute('SELECT id FROM tags WHERE name = ? AND parent_id IS NULL AND id != ?', (name, folder_id))
        if c.fetchone():
            return jsonify({'success': False, 'message': 'そのフォルダ名は既に使用されています'})
        
        # フォルダ更新
        c.execute('UPDATE tags SET name = ? WHERE id = ?', (name, folder_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'フォルダが更新されました'})
        
    except Exception as e:
        logger.error(f"タグフォルダ編集エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'フォルダの編集に失敗しました'})

# チャット管理画面用のユーザータグ取得API
@app.route('/admin/api/user-tags/<line_user_id>')
@admin_required
def api_user_tags(line_user_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # ユーザーが存在するか確認
        c.execute('SELECT line_user_id FROM users WHERE line_user_id = ?', (line_user_id,))
        user = c.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'ユーザーが見つかりません'}), 404
        
        # ユーザーに紐づくタグ一覧を取得（フォルダ名も含む）
        c.execute('''
            SELECT t.id, t.name, t.parent_id, p.name as folder_name
            FROM tags t
            JOIN user_tags ut ON t.id = ut.tag_id
            LEFT JOIN tags p ON t.parent_id = p.id
            WHERE ut.line_user_id = ?
            ORDER BY p.name, t.name
        ''', (line_user_id,))
        
        tags = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify({'success': True, 'tags': tags})
    except Exception as e:
        logger.error(f"ユーザータグ取得エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 全タグ一覧取得API（フォルダ含む）
@app.route('/admin/api/all-tags')
@admin_required
def api_all_tags():
    try:
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ一覧を取得
        c.execute('''
            SELECT id, name, 1 as is_folder, sort_order, created_at
            FROM tag_folders
            ORDER BY sort_order, name
        ''')
        folders = [dict(row) for row in c.fetchall()]
        
        # タグ一覧を取得
        c.execute('''
            SELECT t.id, t.name, t.folder_id, 0 as is_folder, t.created_at,
                   COUNT(ut.id) as user_count
            FROM tags t
            LEFT JOIN user_tags ut ON t.id = ut.tag_id
            GROUP BY t.id
            ORDER BY t.name
        ''')
        tags = [dict(row) for row in c.fetchall()]
        
        # フォルダとタグを統合
        all_items = folders + tags
        
        conn.close()
        
        return jsonify({'success': True, 'tags': all_items, 'folders': folders})
    except Exception as e:
        logger.error(f"全タグ取得エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ユーザーのタグ保存API
@app.route('/admin/api/save-user-tags', methods=['POST'])
@admin_required
def api_save_user_tags():
    data = request.json
    line_user_id = data.get('user_id')
    tag_ids = data.get('tag_ids', [])
    
    if not line_user_id:
        return jsonify({'success': False, 'error': 'ユーザーIDは必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # ユーザーが存在するか確認
        c.execute('SELECT line_user_id FROM users WHERE line_user_id = ?', (line_user_id,))
        user = c.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'ユーザーが見つかりません'}), 404
        
        # 現在のタグ関連をすべて削除
        c.execute('DELETE FROM user_tags WHERE line_user_id = ?', (line_user_id,))
        
        # 新しいタグ関連を追加
        for tag_id in tag_ids:
            c.execute('INSERT INTO user_tags (line_user_id, tag_id) VALUES (?, ?)', (line_user_id, tag_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"ユーザータグ保存エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 対応マーク管理画面
@app.route('/admin/status-markers')
@admin_required
def admin_status_markers():
    conn = get_db()
    c = conn.cursor()
    
    # 対応マーク一覧を取得
    c.execute('''
        SELECT * FROM status_markers
        ORDER BY order_index, created_at
    ''')
    markers = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return render_template('admin/status_markers.html', markers=markers)

# 対応マーク作成API
@app.route('/admin/status-markers/create', methods=['POST'])
@admin_required
def create_status_marker():
    name = request.form.get('name')
    color = request.form.get('color', '#808080')
    
    if not name:
        return jsonify({'success': False, 'error': '対応マーク名は必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # 最大の順序を取得
        c.execute('SELECT MAX(order_index) as max_order FROM status_markers')
        max_order = c.fetchone()['max_order'] or 0
        
        # 新しい対応マークを追加
        c.execute('''
            INSERT INTO status_markers (name, color, order_index, created_at)
            VALUES (?, ?, ?, datetime("now"))
        ''', (name, color, max_order + 1))
        
        marker_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'id': marker_id})
    except Exception as e:
        logger.error(f"対応マーク作成エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 対応マーク編集API
@app.route('/admin/status-markers/edit/<int:marker_id>', methods=['POST'])
@admin_required
def edit_status_marker(marker_id):
    name = request.form.get('name')
    color = request.form.get('color')
    
    if not name:
        return jsonify({'success': False, 'error': '対応マーク名は必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # 対応マークが存在するか確認
        c.execute('SELECT id FROM status_markers WHERE id = ?', (marker_id,))
        marker = c.fetchone()
        if not marker:
            return jsonify({'success': False, 'error': '対応マークが見つかりません'}), 404
        
        # 対応マークを更新
        c.execute('''
            UPDATE status_markers
            SET name = ?, color = ?
            WHERE id = ?
        ''', (name, color, marker_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"対応マーク更新エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 対応マーク削除API
@app.route('/admin/status-markers/delete/<int:marker_id>', methods=['POST'])
@admin_required
def delete_status_marker(marker_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # 対応マークが存在するか確認
        c.execute('SELECT id FROM status_markers WHERE id = ?', (marker_id,))
        marker = c.fetchone()
        if not marker:
            return jsonify({'success': False, 'error': '対応マークが見つかりません'}), 404
        
        # 関連するuser_status_markersを削除
        c.execute('DELETE FROM user_status_markers WHERE marker_id = ?', (marker_id,))
        
        # 対応マークを削除
        c.execute('DELETE FROM status_markers WHERE id = ?', (marker_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"対応マーク削除エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 対応マーク並び替えAPI
@app.route('/admin/status-markers/reorder', methods=['POST'])
@admin_required
def reorder_status_markers():
    try:
        data = request.json
        marker_order = data.get('marker_order', [])
        
        if not marker_order:
            return jsonify({'success': False, 'error': '並び替え情報が不正です'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        # 各対応マークに順序情報を保存
        for i, marker_id in enumerate(marker_order):
            c.execute('UPDATE status_markers SET order_index = ? WHERE id = ?', (i, marker_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"対応マーク並び替えエラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ユーザーに対応マークを設定するAPI
@app.route('/admin/api/save-user-status-marker', methods=['POST'])
@admin_required
def api_save_user_status_marker():
    data = request.json
    line_user_id = data.get('user_id')
    marker_id = data.get('marker_id')
    
    if not line_user_id or marker_id is None:
        return jsonify({'success': False, 'error': 'ユーザーIDと対応マークIDは必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # ユーザーが存在するか確認
        c.execute('SELECT line_user_id FROM users WHERE line_user_id = ?', (line_user_id,))
        user = c.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'ユーザーが見つかりません'}), 404
        
        # 現在の対応マークを削除
        c.execute('DELETE FROM user_status_markers WHERE line_user_id = ?', (line_user_id,))
        
        # 新しい対応マークを設定
        if int(marker_id) > 0:  # マーカーIDが0以上の場合のみ設定
            c.execute('''
                INSERT INTO user_status_markers (line_user_id, marker_id)
                VALUES (?, ?)
            ''', (line_user_id, marker_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"ユーザー対応マーク保存エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ユーザーの対応マーク取得API
@app.route('/admin/api/user-status-marker/<line_user_id>')
@admin_required
def api_user_status_marker(line_user_id):
    try:
        conn = get_db()
        c = conn.cursor()
        
        # ユーザーが存在するか確認
        c.execute('SELECT line_user_id FROM users WHERE line_user_id = ?', (line_user_id,))
        user = c.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'ユーザーが見つかりません'}), 404
        
        # ユーザーの対応マークを取得
        c.execute('''
            SELECT sm.id, sm.name, sm.color
            FROM status_markers sm
            JOIN user_status_markers usm ON sm.id = usm.marker_id
            WHERE usm.line_user_id = ?
            LIMIT 1
        ''', (line_user_id,))
        
        marker = c.fetchone()
        conn.close()
        
        if marker:
            return jsonify({'success': True, 'marker': dict(marker)})
        else:
            return jsonify({'success': True, 'marker': None})
    except Exception as e:
        logger.error(f"ユーザー対応マーク取得エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 全対応マーク一覧取得API
@app.route('/admin/api/all-status-markers')
@admin_required
def api_all_status_markers():
    try:
        conn = get_db()
        c = conn.cursor()
        
        # すべての対応マークを取得
        c.execute('''
            SELECT id, name, color
            FROM status_markers
            ORDER BY order_index, created_at
        ''')
        
        markers = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify({'success': True, 'markers': markers})
    except Exception as e:
        logger.error(f"全対応マーク取得エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/api/update-user-status-marker', methods=['POST'])
@admin_required
def api_update_user_status_marker():
    data = request.json
    user_id = data.get('user_id')
    marker_id = data.get('marker_id')
    
    if not user_id:
        return jsonify({'success': False, 'error': 'ユーザーIDは必須です'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # 既存の対応マークを削除
        c.execute('DELETE FROM user_status_markers WHERE line_user_id = ?', (user_id,))
        
        # 新しい対応マークを設定（marker_idがNoneでない場合）
        if marker_id:
            c.execute('INSERT INTO user_status_markers (line_user_id, marker_id) VALUES (?, ?)', 
                     (user_id, marker_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"対応マーク更新エラー: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/api/status-markers')
@admin_required
def api_status_markers():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, name, color FROM status_markers ORDER BY order_index ASC')
        
        markers = []
        for row in c.fetchall():
            markers.append({
                'id': row['id'],
                'name': row['name'],
                'color': row['color']
            })
        
        conn.close()
        return jsonify({'success': True, 'markers': markers})
    except Exception as e:
        logger.error(f"対応マーク一覧取得エラー: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# テンプレート管理機能
@app.route('/admin/templates')
@admin_required
def admin_templates():
    """テンプレート管理画面"""
    folder_id = request.args.get('folder_id', type=int)
    search_term = request.args.get('search', '')
    
    conn = get_db()
    c = conn.cursor()
    
    # フォルダ一覧とテンプレート数を取得
    c.execute('''
        SELECT f.*, 
               COALESCE(COUNT(t.id), 0) as template_count
        FROM template_folders f
        LEFT JOIN message_templates t ON f.id = t.folder_id
        GROUP BY f.id
        ORDER BY f.sort_order, f.name
    ''')
    folders_raw = c.fetchall()
    
    # フォルダデータを辞書に変換
    folders = [dict(folder) for folder in folders_raw]
    
    # デフォルトフォルダ選択
    if not folder_id and folders:
        folder_id = folders[0]['id']
    
    # テンプレート一覧を取得
    templates = []
    if folder_id:
        query = '''
            SELECT t.*, f.name as folder_name
            FROM message_templates t
            JOIN template_folders f ON t.folder_id = f.id
            WHERE t.folder_id = ?
        '''
        params = [folder_id]
        
        if search_term:
            query += ' AND (t.name LIKE ? OR t.preview_text LIKE ?)'
            params.extend([f'%{search_term}%', f'%{search_term}%'])
            
        query += ' ORDER BY t.sort_order, t.created_at DESC'
        
        c.execute(query, params)
        templates_raw = c.fetchall()
        
        # テンプレートデータを辞書に変換して日付を処理
        templates = []
        for template in templates_raw:
            template_dict = dict(template)
            # created_atが文字列の場合の処理
            if template_dict['created_at']:
                if isinstance(template_dict['created_at'], str):
                    # 文字列から日付部分を抽出して先頭の0を削除
                    date_str = template_dict['created_at'][:10]  # YYYY-MM-DD
                    try:
                        from datetime import datetime
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        template_dict['created_at'] = f"{date_obj.year}-{date_obj.month}-{date_obj.day}"
                    except:
                        template_dict['created_at'] = date_str
                else:
                    # datetimeオブジェクトの場合
                    template_dict['created_at'] = f"{template_dict['created_at'].year}-{template_dict['created_at'].month}-{template_dict['created_at'].day}"
            templates.append(template_dict)
    
    conn.close()
    
    return render_template('admin/templates.html', 
                         folders=folders, 
                         templates=templates,
                         selected_folder_id=folder_id,
                         search_term=search_term)

@app.route('/admin/templates/folders/create', methods=['POST'])
@admin_required
def create_template_folder():
    """テンプレートフォルダ作成"""
    try:
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#FFA500')
        
        if not name:
            return jsonify({'success': False, 'message': 'フォルダ名は必須です'})
        
        # 「未分類」フォルダ名は予約語として使用不可
        if name == '未分類':
            return jsonify({'success': False, 'message': '「未分類」は予約語のため使用できません'})
        
        conn = get_db()
        c = conn.cursor()
        
        # 最大ソート順を取得
        c.execute('SELECT MAX(sort_order) FROM template_folders')
        max_order = c.fetchone()[0] or 0
        
        # フォルダ作成
        c.execute('''
            INSERT INTO template_folders (name, color, sort_order)
            VALUES (?, ?, ?)
        ''', (name, color, max_order + 1))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'フォルダが作成されました'})
        
    except Exception as e:
        logger.error(f"フォルダ作成エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'フォルダの作成に失敗しました'})

@app.route('/admin/templates/folders/edit/<int:folder_id>', methods=['POST'])
@admin_required
def edit_template_folder(folder_id):
    """テンプレートフォルダ編集"""
    try:
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#FFA500')
        
        if not name:
            return jsonify({'success': False, 'message': 'フォルダ名は必須です'})
        
        # 「未分類」フォルダ名は予約語として使用不可
        if name == '未分類':
            return jsonify({'success': False, 'message': '「未分類」は予約語のため使用できません'})
        
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ存在確認
        c.execute('SELECT id FROM template_folders WHERE id = ?', (folder_id,))
        if not c.fetchone():
            return jsonify({'success': False, 'message': 'フォルダが見つかりません'})
        
        # フォルダ更新
        c.execute('''
            UPDATE template_folders 
            SET name = ?, color = ?
            WHERE id = ?
        ''', (name, color, folder_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'フォルダが更新されました'})
        
    except Exception as e:
        logger.error(f"フォルダ更新エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'フォルダの更新に失敗しました'})

@app.route('/admin/templates/folders/delete/<int:folder_id>', methods=['POST'])
@admin_required
def delete_template_folder(folder_id):
    """テンプレートフォルダ削除"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ存在確認
        c.execute('SELECT id, name FROM template_folders WHERE id = ?', (folder_id,))
        folder = c.fetchone()
        if not folder:
            return jsonify({'success': False, 'message': 'フォルダが見つかりません'})
        
        # 「未分類」フォルダは削除不可
        if folder['name'] == '未分類':
            return jsonify({'success': False, 'message': '「未分類」フォルダは削除できません'})
        
        # フォルダ内のテンプレート数を確認
        c.execute('SELECT COUNT(*) as count FROM message_templates WHERE folder_id = ?', (folder_id,))
        template_count = c.fetchone()[0]
        
        if template_count > 0:
            return jsonify({'success': False, 'message': f'このフォルダには{template_count}個のテンプレートが含まれています。先にテンプレートを削除または移動してください。'})
        
        # フォルダ削除
        c.execute('DELETE FROM template_folders WHERE id = ?', (folder_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'フォルダが削除されました'})
        
    except Exception as e:
        logger.error(f"フォルダ削除エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'フォルダの削除に失敗しました'})

@app.route('/admin/templates/create', methods=['GET', 'POST'])
@admin_required
def create_template():
    """テンプレート作成"""
    if request.method == 'GET':
        # GET リクエストの場合は作成ページを表示
        folder_id = request.args.get('folder_id', type=int)
        
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ一覧を取得
        c.execute('SELECT * FROM template_folders ORDER BY sort_order, name')
        folders = [dict(folder) for folder in c.fetchall()]
        
        conn.close()
        
        # LINE公式アカウント情報を取得
        line_bot_info = get_line_bot_info()
        
        return render_template('admin/template_create.html', 
                             folders=folders, 
                             selected_folder_id=folder_id,
                             line_bot_info=line_bot_info)
    
    # POST リクエストの場合はテンプレート作成処理
    try:
        name = request.form.get('name', '').strip()
        template_type = request.form.get('type', 'text')
        content = request.form.get('content', '').strip()
        folder_id = request.form.get('folder_id', type=int)
        
        if not name:
            return jsonify({'success': False, 'message': 'テンプレート名は必須です'})
        
        if not folder_id:
            return jsonify({'success': False, 'message': 'フォルダの選択は必須です'})
        
        # 画像タイプの場合の処理
        image_url = None
        if template_type == 'image':
            # 画像ファイルがアップロードされているかチェック
            if 'image_file' not in request.files:
                return jsonify({'success': False, 'message': '画像ファイルが選択されていません'})
            
            image_file = request.files['image_file']
            if image_file.filename == '':
                return jsonify({'success': False, 'message': '画像ファイルが選択されていません'})
            
            # ファイルサイズチェック（1MB）
            if len(image_file.read()) > 1024 * 1024:
                return jsonify({'success': False, 'message': 'ファイルサイズが1MBを超えています'})
            
            # ファイルポインタを先頭に戻す
            image_file.seek(0)
            
            # ファイル拡張子チェック
            allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
            file_extension = image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else ''
            if file_extension not in allowed_extensions:
                return jsonify({'success': False, 'message': '対応していないファイル形式です。PNG、JPG、JPEG、GIF、WEBPファイルを選択してください'})
            
            # 画像を保存
            import os
            import uuid
            from datetime import datetime
            
            # アップロードディレクトリを作成
            upload_dir = os.path.join('static', 'uploads', 'templates')
            os.makedirs(upload_dir, exist_ok=True)
            
            # ユニークなファイル名を生成
            unique_filename = f"{uuid.uuid4().hex}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_extension}"
            file_path = os.path.join(upload_dir, unique_filename)
            
            # ファイルを保存
            image_file.save(file_path)
            
            # URLを生成（Renderの場合は絶対URLが必要）
            image_url = f"{request.url_root}static/uploads/templates/{unique_filename}"
            
            # contentが空の場合は画像URLをcontentに設定
            if not content:
                content = image_url
        else:
            # テキストタイプの場合はcontentが必須
            if not content:
                return jsonify({'success': False, 'message': 'テンプレート内容は必須です'})
        
        # プレビューテキストを生成
        preview_text = content
        if template_type == 'text':
            # 改行を保持したプレビューテキスト
            preview_text = content.replace('\n', ' ').strip()
            preview_text = preview_text[:100] + ('...' if len(preview_text) > 100 else '')
        elif template_type == 'image':
            preview_text = f"画像: {content}" if content != image_url else "画像メッセージ"
        elif template_type == 'video':
            preview_text = f"動画: {content}"
        elif template_type in ['carousel', 'flex']:
            preview_text = f"{template_type.capitalize()}メッセージ"
        
        conn = get_db()
        c = conn.cursor()
        
        # フォルダ存在確認
        c.execute('SELECT id FROM template_folders WHERE id = ?', (folder_id,))
        if not c.fetchone():
            return jsonify({'success': False, 'message': '指定されたフォルダが存在しません'})
        
        # 最大ソート順を取得
        c.execute('SELECT MAX(sort_order) FROM message_templates WHERE folder_id = ?', (folder_id,))
        max_order = c.fetchone()[0] or 0
        
        # テンプレート作成（image_urlカラムも追加）
        c.execute('''
            INSERT INTO message_templates (folder_id, name, type, content, preview_text, image_url, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (folder_id, name, template_type, content, preview_text, image_url, max_order + 1))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'テンプレートが作成されました'})
        
    except Exception as e:
        logger.error(f"テンプレート作成エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'テンプレートの作成に失敗しました'})

@app.route('/admin/templates/delete', methods=['POST'])
@admin_required
def delete_template():
    """テンプレート削除（単体）"""
    try:
        data = request.get_json()
        template_id = data.get('template_id')
        
        if not template_id:
            return jsonify({'success': False, 'message': 'テンプレートIDが必要です'})
        
        conn = get_db()
        c = conn.cursor()
        
        # テンプレート存在確認
        c.execute('SELECT id FROM message_templates WHERE id = ?', (template_id,))
        if not c.fetchone():
            return jsonify({'success': False, 'message': 'テンプレートが見つかりません'})
        
        # テンプレート削除
        c.execute('DELETE FROM message_templates WHERE id = ?', (template_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'テンプレートが削除されました'})
        
    except Exception as e:
        logger.error(f"テンプレート削除エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'テンプレートの削除に失敗しました'})

@app.route('/admin/templates/delete-multiple', methods=['POST'])
@admin_required
def delete_templates():
    """テンプレート削除（複数）"""
    try:
        data = request.get_json()
        template_ids = data.get('template_ids', [])
        
        if not template_ids:
            return jsonify({'success': False, 'message': '削除するテンプレートを選択してください'})
        
        conn = get_db()
        c = conn.cursor()
        
        # 複数削除
        placeholders = ','.join(['?' for _ in template_ids])
        c.execute(f'DELETE FROM message_templates WHERE id IN ({placeholders})', template_ids)
        
        deleted_count = c.rowcount
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'{deleted_count}個のテンプレートが削除されました'})
        
    except Exception as e:
        logger.error(f"テンプレート一括削除エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'テンプレートの削除に失敗しました'})

@app.route('/admin/templates/edit/<int:template_id>', methods=['GET', 'POST'])
@admin_required
def edit_template(template_id):
    """テンプレート編集"""
    conn = get_db()
    c = conn.cursor()
    
    # テンプレート情報を取得
    c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
    template = c.fetchone()
    
    if not template:
        # GETリクエストでテンプレートが見つからない場合はエラーページへ
        if request.method == 'GET':
            flash('テンプレートが見つかりません', 'error')
            return redirect(url_for('admin_templates'))
        # POSTリクエストでテンプレートが見つからない場合はJSONエラー
        conn.close() # DB接続を閉じる
        return jsonify({'success': False, 'message': 'テンプレートが見つかりません'}), 404
    
    if request.method == 'GET':
        # フォルダ一覧を取得
        c.execute('SELECT * FROM template_folders ORDER BY sort_order, name')
        folders = [dict(folder) for folder in c.fetchall()]
        conn.close()
        line_bot_info = get_line_bot_info()
        return render_template('admin/template_edit.html', 
                             template=dict(template),
                             folders=folders,
                             line_bot_info=line_bot_info)
    
    # POST リクエストの場合はテンプレート更新処理
    try:
        name = request.form.get('name', '').strip()
        template_type = request.form.get('type', 'text')
        # 画像タイプの場合、フロントエンドからcontentは送られてこないか空文字のはず
        # ただし、他のタイプでは必須なので、ここで取得はしておく
        content = request.form.get('content', '').strip()
        folder_id = request.form.get('folder_id', type=int)
        image_file = request.files.get('image_file')

        if not name:
            conn.close()
            return jsonify({'success': False, 'message': 'テンプレート名は必須です'}), 400
        
        if not folder_id:
            conn.close()
            return jsonify({'success': False, 'message': 'フォルダの選択は必須です'}), 400
        
        # フォルダ存在確認
        c.execute('SELECT id FROM template_folders WHERE id = ?', (folder_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': '指定されたフォルダが見つかりません'}), 400

        current_image_url = template['image_url'] # 更新前の画像URL
        new_image_url = current_image_url # 特に大きな変更がなければ元のURLを維持
        
        # プレビューテキストと画像URLの処理
        preview_text = ""
        if template_type == 'text':
            if not content: # テキストタイプで本文が空の場合
                conn.close()
                return jsonify({'success': False, 'message': 'テキストテンプレートの本文は必須です'}), 400
            preview_text = content.replace('\\n', ' ').strip()
            preview_text = preview_text[:100] + ('...' if len(preview_text) > 100 else '')
            new_image_url = None # テキストテンプレートなので画像URLはNULL
        
        elif template_type == 'image':
            preview_text = "画像テンプレート" # デフォルトのプレビューテキスト
            if image_file and allowed_file(image_file.filename):
                # 新しい画像がアップロードされた場合
                # 既存の画像を削除（もしあれば）
                if current_image_url:
                    try:
                        # URLからファイルパスを推測（static/uploads/templates/filename.ext の形式を想定）
                        # url_forで生成された相対パスまたは絶対パスを考慮
                        filename_from_url = current_image_url.split('/')[-1]
                        # UPLOAD_FOLDER_TEMPLATES は 'static/uploads/templates' のような相対パス
                        # os.path.join で workspace からの相対パスを正しく作る
                        old_filepath = os.path.join(app.config['UPLOAD_FOLDER_TEMPLATES'], filename_from_url)
                        
                        if os.path.exists(old_filepath):
                            os.remove(old_filepath)
                            logger.info(f"古い画像ファイルを削除しました: {old_filepath}")
                        else:
                            logger.warning(f"削除対象の古い画像ファイルが見つかりません: {old_filepath} (URL: {current_image_url})")
                    except Exception as e:
                        logger.error(f"古い画像の削除に失敗しました: {str(e)}")

                # 新しい画像を保存
                # ファイル名を一意にするためにタイムスタンプとマイクロ秒を追加
                filename_base, file_extension = os.path.splitext(image_file.filename)
                filename = secure_filename(f"{filename_base}_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}{file_extension}")
                save_path = os.path.join(app.config['UPLOAD_FOLDER_TEMPLATES'], filename)
                try:
                    if not os.path.exists(app.config['UPLOAD_FOLDER_TEMPLATES']):
                        os.makedirs(app.config['UPLOAD_FOLDER_TEMPLATES'], exist_ok=True)
                    image_file.save(save_path)
                    # `url_for` で生成するパスは `static` から始まる
                    new_image_url = url_for('static', filename=f'uploads/templates/{filename}', _external=True)
                    logger.info(f"新しい画像ファイルを保存しました: {save_path}, URL: {new_image_url}")
                    preview_text = f"画像: {filename}" # プレビューにはファイル名を使用
                except Exception as e:
                    logger.error(f"画像ファイルの保存に失敗しました: {str(e)}")
                    conn.close()
                    return jsonify({'success': False, 'message': f'画像ファイルの保存に失敗しました。'}), 500 # 詳細なエラーはクライアントに返さない
            elif not current_image_url and not image_file:
                 # 画像が無く、新しいファイルもアップロードされていない場合 (テンプレート作成時や、画像なしテンプレートを編集中など)
                 # フロントエンドのバリデーションでここは通らないはずだが、念のため
                 conn.close()
                 return jsonify({'success': False, 'message': '画像タイプのテンプレートには画像ファイルが必要です'}), 400
            elif current_image_url: # 新しいファイルがアップロードされず、既存の画像URLがある場合
                preview_text = f"画像: {current_image_url.split('/')[-1]}"
            
            # 画像タイプの場合、本文(content)は常に空にする。画像URL(new_image_url)にパスが入る
            content = "" 
            
        elif template_type == 'video':
            if not content: # 動画タイプでURLが空の場合
                conn.close()
                return jsonify({'success': False, 'message': '動画テンプレートのURLは必須です'}), 400
            preview_text = f"動画: {content}"
            new_image_url = None # 動画テンプレートなので画像URLはNULL
        elif template_type in ['carousel', 'flex']:
            if not content: # カルーセル・Flexで本文が空の場合
                conn.close()
                return jsonify({'success': False, 'message': f'{template_type.capitalize()}メッセージの本文は必須です'}), 400
            preview_text = f"{template_type.capitalize()}メッセージ"
            new_image_url = None # カルーセル・Flexなので画像URLはNULL
        else:
            # 未知のテンプレートタイプ
            conn.close()
            return jsonify({'success': False, 'message': f'未知のテンプレートタイプです: {template_type}'}), 400
        
        # テンプレート更新
        c.execute('''
            UPDATE message_templates 
            SET folder_id = ?, name = ?, type = ?, content = ?, preview_text = ?, image_url = ?, updated_at = datetime('now')
            WHERE id = ?
        ''', (folder_id, name, template_type, content, preview_text, new_image_url, template_id))
        
        conn.commit()
        logger.info(f"テンプレートが正常に更新されました。ID: {template_id}, Name: {name}, Type: {template_type}, Image URL: {new_image_url}")
        
    except Exception as e:
        logger.error(f"テンプレート更新処理中に予期せぬエラー (template_id: {template_id}): {str(e)}", exc_info=True)
        # conn が try ブロックの最初で取得されているので、ここで閉じる
        return jsonify({'success': False, 'message': f'テンプレートの更新中に予期せぬサーバーエラーが発生しました。'}), 500
    finally:
        if conn: # conn が開いている場合のみ閉じる
            try:
                conn.close()
            except Exception as db_close_err: # sqlite3.ProgrammingError のようなエラーをキャッチ
                logger.error(f"データベース接続クローズエラー (edit_template): {str(db_close_err)}")
        
        return jsonify({'success': True, 'message': 'テンプレートが更新されました'})

@app.route('/admin/templates/preview/<int:template_id>')
@admin_required
def preview_template(template_id):
    """テンプレートプレビュー"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
        template = c.fetchone()
        
        if not template:
            return jsonify({'success': False, 'message': 'テンプレートが見つかりません'})
        
        conn.close()
        
        # プレビュー用のデータを整形
        preview_data = {
            'id': template['id'],
            'name': template['name'],
            'type': template['type'],
            'content': template['content'],
            'preview_text': template['preview_text'],
            'image_url': template['image_url'] if 'image_url' in template.keys() else None  # 修正
        }
        
        return jsonify({'success': True, 'template': preview_data})
        
    except Exception as e:
        logger.error(f"テンプレートプレビューエラー: {str(e)}")
        return jsonify({'success': False, 'message': 'プレビューの取得に失敗しました'})

@app.route('/admin/templates/edit-name', methods=['POST'])
@admin_required
def edit_template_name():
    """テンプレート名変更"""
    try:
        data = request.get_json()
        template_id = data.get('template_id')
        new_name = data.get('name', '').strip()
        
        if not template_id or not new_name:
            return jsonify({'success': False, 'message': 'テンプレートIDと名前は必須です'})
        
        conn = get_db()
        c = conn.cursor()
        
        # テンプレート存在確認
        c.execute('SELECT id FROM message_templates WHERE id = ?', (template_id,))
        if not c.fetchone():
            return jsonify({'success': False, 'message': 'テンプレートが見つかりません'})
        
        # テンプレート名更新
        c.execute('''
            UPDATE message_templates 
            SET name = ?, updated_at = datetime('now')
            WHERE id = ?
        ''', (new_name, template_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'テンプレート名が更新されました'})
        
    except Exception as e:
        logger.error(f"テンプレート名更新エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'テンプレート名の更新に失敗しました'})

@app.route('/api/search-friends', methods=['POST'])
@admin_required
def search_friends():
    """友だち検索API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        
        logger.info(f"友だち検索リクエスト: query='{query}'")
        
        if not query:
            return jsonify({'success': True, 'users': []})
        
        conn = get_db()
        c = conn.cursor()
        
        # まず全ユーザー数を確認
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        logger.info(f"総ユーザー数: {total_users}")
        
        # line_user_idがnullでないユーザー数を確認
        c.execute('SELECT COUNT(*) FROM users WHERE line_user_id IS NOT NULL')
        valid_users = c.fetchone()[0]
        logger.info(f"有効なline_user_idを持つユーザー数: {valid_users}")
        
        # ユーザーテーブルから名前で検索（line_user_idがnullでないもののみ）
        c.execute('''
            SELECT line_user_id, name, profile_image_url
            FROM users 
            WHERE name LIKE ? AND line_user_id IS NOT NULL
            ORDER BY name
            LIMIT 10
        ''', (f'%{query}%',))
        
        rows = c.fetchall()
        logger.info(f"検索結果件数: {len(rows)}")
        
        users = []
        for row in rows:
            user_data = {
                'id': row[0],  # line_user_idを使用
                'name': row[1],
                'avatar': row[2]  # profile_image_url
            }
            users.append(user_data)
            logger.info(f"検索結果ユーザー: {user_data}")
        
        conn.close()
        
        logger.info(f"最終返却データ: {users}")
        return jsonify({'success': True, 'users': users})
        
    except Exception as e:
        logger.error(f"友だち検索エラー: {str(e)}")
        return jsonify({'success': False, 'message': '検索に失敗しました', 'users': []})

@app.route('/admin/templates/test-send', methods=['POST'])
@admin_required
def test_send_template():
    """テンプレートのテスト送信"""
    try:
        data = request.get_json()
        logger.info(f"テスト送信リクエスト受信: {data}")
        
        template_id = data.get('template_id')
        user_id = data.get('user_id')
        
        logger.info(f"受信データ: template_id={template_id} (type: {type(template_id)}), user_id={user_id} (type: {type(user_id)})")
        
        if not template_id or not user_id:
            logger.error(f"必須パラメータ不足: template_id={template_id}, user_id={user_id}")
            return jsonify({'success': False, 'message': 'テンプレートIDとユーザーIDは必須です'})
        
        conn = get_db()
        c = conn.cursor()
        
        # テンプレート情報を取得
        c.execute('SELECT * FROM message_templates WHERE id = ?', (template_id,))
        template = c.fetchone()
        
        if not template:
            logger.error(f"テンプレートが見つかりません: template_id={template_id}")
            return jsonify({'success': False, 'message': 'テンプレートが見つかりません'})
        
        logger.info(f"テンプレート取得成功: {template['name']}")
        
        # ユーザー情報を取得
        c.execute('SELECT name FROM users WHERE line_user_id = ?', (user_id,))
        user = c.fetchone()
        
        if not user:
            logger.error(f"ユーザーが見つかりません: user_id={user_id}")
            return jsonify({'success': False, 'message': 'ユーザーが見つかりません'})
        
        logger.info(f"ユーザー取得成功: {user['name']}")
        
        conn.close()
        
        # テンプレートの内容を取得
        template_content = template['content']
        template_type = template['type']
        # SQLite3のRowオブジェクトには.get()が使えないため、安全にアクセス
        template_image_url = template['image_url'] if 'image_url' in template.keys() else None
        
        logger.info(f"送信準備: type={template_type}, content={template_content[:50] if template_content else 'None'}..., image_url={template_image_url}")
        
        # LINEメッセージを送信
        try:
            if template_type == 'text':
                # テキストメッセージの送信
                success = send_line_message(user_id, template_content)
            elif template_type == 'image':
                # 画像メッセージの送信（image_urlを優先、なければcontentを使用）
                image_url = template_image_url or template_content
                if not image_url:
                    return jsonify({'success': False, 'message': '画像URLが設定されていません'})
                success = send_line_image_message(user_id, image_url)
            else:
                # その他のタイプは現在未対応
                return jsonify({'success': False, 'message': f'{template_type}タイプのメッセージは現在未対応です'})
            
            if success:
                logger.info(f"テスト送信成功: テンプレート{template_id} → ユーザー{user_id}")
                return jsonify({'success': True, 'message': 'テストメッセージを送信しました'})
            else:
                logger.error(f"LINE送信失敗: テンプレート{template_id} → ユーザー{user_id}")
                return jsonify({'success': False, 'message': 'メッセージの送信に失敗しました'})
                
        except Exception as send_error:
            logger.error(f"LINE送信エラー: {str(send_error)}")
            return jsonify({'success': False, 'message': 'LINE送信でエラーが発生しました'})
        
    except Exception as e:
        logger.error(f"テスト送信エラー: {str(e)}")
        return jsonify({'success': False, 'message': 'テスト送信中にエラーが発生しました'})

# application = socketio.wsgi_app

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=8000)

# SocketIOイベントハンドラ
@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')

# 【デバッグ用】タグテーブルの詳細情報を取得
@app.route('/admin/api/debug-tags')
@admin_required  
def api_debug_tags():
    try:
        conn = get_db()
        c = conn.cursor()
        
        # テーブル構造を確認
        c.execute("PRAGMA table_info(tags)")
        table_info = [dict(row) for row in c.fetchall()]
        
        # 全データを取得
        c.execute('SELECT * FROM tags ORDER BY id')
        all_tags = [dict(row) for row in c.fetchall()]
        
        # フォルダとタグの分類
        folders = [tag for tag in all_tags if tag['parent_id'] is None]
        child_tags = [tag for tag in all_tags if tag['parent_id'] is not None]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'table_structure': table_info,
            'total_count': len(all_tags),
            'folder_count': len(folders),
            'tag_count': len(child_tags),
            'all_tags': all_tags,
            'folders': folders,
            'child_tags': child_tags
        })
    except Exception as e:
        logger.error(f"デバッグ情報取得エラー: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
