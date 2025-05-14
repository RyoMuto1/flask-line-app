import os
import sqlite3
import requests
import jwt    # ← 追加
from flask import (
    Flask, render_template, request,
    redirect, jsonify, session, Response
)
from dotenv import load_dotenv
import logging  # 追加
from werkzeug.security import generate_password_hash, check_password_hash

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# .env をロード
load_dotenv()

app = Flask(__name__)
# セッション用の鍵
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# DB 初期化
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

    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
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
        init_db()
        logger.info("データベースの初期化が完了しました")
    except Exception as e:
        logger.error(f"データベース初期化エラー: {str(e)}")
        raise

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
    params = {
        'response_type':'code',
        'client_id':LINE_LOGIN_CHANNEL_ID,
        'redirect_uri':LINE_REDIRECT_URI,
        'scope':'openid profile',
        'state':'12345abcde'
    }
    url = 'https://access.line.me/oauth2/v2.1/authorize?' + '&'.join(f'{k}={v}' for k,v in params.items())
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_res = requests.post(
        'https://api.line.me/oauth2/v2.1/token',
        headers={'Content-Type':'application/x-www-form-urlencoded'},
        data={
            'grant_type':'authorization_code',
            'code':code,
            'redirect_uri':LINE_REDIRECT_URI,
            'client_id':LINE_LOGIN_CHANNEL_ID,
            'client_secret':LINE_LOGIN_CHANNEL_SECRET
        }
    )
    token_data = token_res.json()
    logger.debug("🐛 token_data: %s", token_data)
    id_token = token_data.get('id_token')
    if not id_token:
        return Response("id_token が取れませんでした", status=500)

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

    return redirect('/')

@app.route('/mypage')
def mypage():
    try:
        if 'line_user_id' not in session:
            return redirect('/login')
        conn = get_db()
        c = conn.cursor()
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
                               user_name=session.get('line_user_name', 'ゲスト'),
                               orders=orders)
    except Exception as e:
        logger.error(f"マイページエラー: {str(e)}")
        return "エラーが発生しました。しばらく経ってから再度お試しください。", 500

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
        
        return render_template('admin/login.html', error='メールアドレスまたはパスワードが正しくありません。')
    
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect('/admin/login')
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT id, name, school_name, event_date, budget, created_at
        FROM orders
        ORDER BY created_at DESC
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
