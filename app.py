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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("registration_linksテーブルを作成しました")

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

    # タグ管理テーブルの作成
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tags'")
    if not c.fetchone():
        logger.info("tagsテーブルが存在しないため、新規作成します")
        c.execute('''
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("tagsテーブルを作成しました")
    else:
        # 既存のtagsテーブルからcolorカラムを削除（もし存在すれば）
        c.execute("PRAGMA table_info(tags)")
        columns = [row[1] for row in c.fetchall()]
        if 'color' in columns:
            logger.info("tagsテーブルからcolorカラムを削除します")
            # SQLiteはカラム削除が直接できないので一時テーブルでマイグレーション
            c.execute('''
                CREATE TABLE tags_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            c.execute('''
                INSERT INTO tags_new (id, name, created_at)
                SELECT id, name, created_at FROM tags
            ''')
            c.execute('DROP TABLE tags')
            c.execute('ALTER TABLE tags_new RENAME TO tags')
            conn.commit()
            logger.info("tagsテーブルのcolorカラム削除完了")

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
        
        # データベース初期化
        init_db()
        logger.info("データベースの初期化が完了しました")
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
    
    # 登録リンク一覧を取得（登録者数も含める）
    cursor.execute('''
        SELECT rl.*, COUNT(ur.id) as registration_count
        FROM registration_links rl
        LEFT JOIN user_registrations ur ON rl.id = ur.registration_link_id
        GROUP BY rl.id
        ORDER BY rl.created_at DESC
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
    return render_template('admin/line_source_analytics.html', registration_links=result_links)

# 新しい登録リンクの作成
@app.route('/admin/line-source-analytics/create-link', methods=['POST'])
@admin_required
def create_registration_link():
    try:
        name = request.form.get('name')
        source = request.form.get('source')
        
        if not name or not source:
            flash('リンク名と流入元は必須です', 'error')
            return redirect(url_for('line_source_analytics'))
        
        # ユニークなリンクコードを生成
        link_code = secrets.token_urlsafe(8)
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO registration_links (name, source, link_code, created_at)
                VALUES (?, ?, ?, datetime('now'))
            ''', (name, source, link_code))
            conn.commit()
            flash('登録リンクを作成しました', 'success')
        except sqlite3.IntegrityError as e:
            logger.error(f"データベースエラー: {str(e)}")
            flash('リンクコードの生成に失敗しました。もう一度お試しください', 'error')
        finally:
            conn.close()
        
        return redirect(url_for('line_source_analytics'))
    except Exception as e:
        logger.error(f"登録リンク作成エラー: {str(e)}")
        flash('エラーが発生しました。もう一度お試しください', 'error')
        return redirect(url_for('line_source_analytics'))

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
    if 'line_user_id' not in session:
        return redirect('/login')
    
    conn = get_db()
    c = conn.cursor()
    
    # 他のユーザーを検索（自分以外）
    c.execute('''
        SELECT *
        FROM users
        WHERE line_user_id != ?
        ORDER BY name
    ''', (session['line_user_id'],))
    
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return render_template('chat/users.html', users=users)

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
    
    # ユーザー一覧を取得（未読メッセージ数と最新メッセージも取得）
    cursor.execute('''
        SELECT u.line_user_id, u.name, u.email, u.profile_image_url, u.created_at,
               (SELECT COUNT(*) FROM admin_chat_messages 
                WHERE line_user_id = u.line_user_id AND is_from_admin = 0 AND read_status = 0) AS unread_count,
               (SELECT message FROM admin_chat_messages 
                WHERE line_user_id = u.line_user_id 
                ORDER BY sent_at DESC LIMIT 1) AS last_message
        FROM users u
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
            'last_message': row['last_message']
        })
    
    conn.close()
    return jsonify({'success': True, 'users': users})

# APIエンドポイント: ユーザー情報取得
@app.route('/admin/api/user/<line_user_id>')
@admin_required
def api_user_info(line_user_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # ユーザー情報を取得
    cursor.execute('''
        SELECT u.*, COUNT(o.id) as order_count
        FROM users u
        LEFT JOIN orders o ON u.line_user_id = o.line_user_id
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
        'order_count': user_row['order_count']
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
    c.execute('''
        SELECT t.*, COUNT(ut.id) as user_count
        FROM tags t
        LEFT JOIN user_tags ut ON t.id = ut.tag_id
        GROUP BY t.id
        ORDER BY t.created_at DESC
    ''')
    tags = [dict(row) for row in c.fetchall()]
    conn.close()
    return render_template('admin/tags.html', tags=tags)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)
else:
    # gunicornから参照されるオブジェクト
    application = socketio.wsgi_app

# SocketIOイベントハンドラ
@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')
