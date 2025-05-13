import os
import sqlite3
import requests
import jwt    # ← 追加
from flask import (
    Flask, render_template, request,
    redirect, jsonify, session, Response
)
from dotenv import load_dotenv


# .env をロード
load_dotenv()

app = Flask(__name__)
# セッション用の鍵
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# DB 初期化
def init_db():
    try:
        # データベースファイルのパスを取得
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
        app.logger.info(f"データベースパス: {db_path}")
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # テーブルが存在するか確認
        c.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='orders'
        ''')
        
        if not c.fetchone():
            # テーブルが存在しない場合のみ作成
            c.execute('''
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    item TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            app.logger.info("ordersテーブルを作成しました")
        else:
            app.logger.info("ordersテーブルは既に存在します")
        
        conn.commit()
        conn.close()
        app.logger.info("データベースの初期化が完了しました")
    except Exception as e:
        app.logger.error(f"データベース初期化エラー: {str(e)}")
        raise

def get_db():
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')
        app.logger.info(f"データベースに接続します: {db_path}")
        
        # データベースファイルの存在確認
        if not os.path.exists(db_path):
            app.logger.warning(f"データベースファイルが存在しません: {db_path}")
            init_db()
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # テーブルの存在確認
        c = conn.cursor()
        c.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='orders'
        ''')
        if not c.fetchone():
            app.logger.warning("ordersテーブルが存在しません")
            init_db()
        
        return conn
    except Exception as e:
        app.logger.error(f"データベース接続エラー: {str(e)}")
        raise

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
    app.logger.debug(f"LINE Push → {res.status_code} {res.text}")

# アプリケーションの初期化
with app.app_context():
    try:
        init_db()
        app.logger.info("データベースの初期化が完了しました")
    except Exception as e:
        app.logger.error(f"データベース初期化エラー: {str(e)}")
        raise

@app.route('/', methods=['GET', 'POST'])
def order_form():
    try:
        # LINEログインしていない場合はログインページへリダイレクト
        if not session.get('line_user_id'):
            return redirect('/login')

        if request.method == 'POST':
            # フォームデータの取得と検証
            required_fields = ['name', 'product_name', 'quantity', 'event_date', 
                             'class_teacher', 'school_name', 'delivery_name', 
                             'postal_code', 'prefecture', 'city', 'address']
            
            # 必須フィールドのチェック
            for field in required_fields:
                if not request.form.get(field):
                    app.logger.error(f"必須フィールドが不足: {field}")
                    return f"必須項目が入力されていません: {field}", 400

            # フォームデータの取得
            form_data = {
                'name': request.form.get('name'),
                'item': request.form.get('product_name'),
                'quantity': request.form.get('quantity'),
                'line_user_id': session['line_user_id']
            }
            
            app.logger.info(f"フォームデータ: {form_data}")

            try:
                # データベースに保存
                conn = get_db()
                c = conn.cursor()
                
                # データの型を確認
                app.logger.info(f"保存するデータ: line_user_id={form_data['line_user_id']}, name={form_data['name']}, item={form_data['item']}, quantity={form_data['quantity']}")
                
                c.execute('''
                    INSERT INTO orders (line_user_id, name, item, quantity)
                    VALUES (?, ?, ?, ?)
                ''', (form_data['line_user_id'], form_data['name'], form_data['item'], form_data['quantity']))
                conn.commit()
                conn.close()
                app.logger.info("データベースへの保存が完了しました")
            except Exception as db_error:
                app.logger.error(f"データベースエラー: {str(db_error)}")
                return f"データベースエラーが発生しました: {str(db_error)}", 500

            try:
                # LINE へお知らせ
                message = f'''
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
                app.logger.info("LINE通知の送信が完了しました")
            except Exception as line_error:
                app.logger.error(f"LINE通知エラー: {str(line_error)}")
                # LINE通知のエラーは注文処理を妨げないようにする
                pass

            return redirect('/thanks')

        return render_template('form.html')
    except Exception as e:
        app.logger.error(f"フォーム処理エラー: {str(e)}")
        return "エラーが発生しました。しばらく経ってから再度お試しください。", 500

@app.route('/thanks')
def thanks():
    return 'ご注文ありがとうございました！'

@app.route('/history')
def history():
    conn = sqlite3.connect('orders.db')
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
    app.logger.debug("📬 webhook hit：%s", request.get_data())
    return jsonify({"status":"ok"})

# LINE Login 設定
LINE_LOGIN_CHANNEL_ID     = os.environ["LINE_LOGIN_CHANNEL_ID"]
LINE_LOGIN_CHANNEL_SECRET = os.environ["LINE_LOGIN_CHANNEL_SECRET"]

# 環境に応じてリダイレクトURIを設定
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
    # トークン取得
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
    app.logger.debug("🐛 token_data: %s", token_data)
    id_token = token_data.get('id_token')
    if not id_token:
        return Response("id_token が取れませんでした", status=500)

    # JWT を検証せずにデコード
    try:
        payload = jwt.decode(id_token, options={"verify_signature": False})
    except Exception as e:
        app.logger.error("JWT decode error: %s", e)
        return Response("ID トークンの解析に失敗しました", status=500)

    user_id   = payload.get('sub')
    user_name = payload.get('name', '（名前なし）')
    if not user_id:
        return Response("ユーザーID(sub) が取得できませんでした", status=500)

    # セッションに保存
    session['line_user_id']   = user_id
    session['line_user_name'] = user_name

    # トップページ（注文フォーム）へリダイレクト
    return redirect('/')

@app.route('/mypage')
def mypage():
    try:
        if 'line_user_id' not in session:
            return redirect('/login')
        
        # データベース接続
        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        
        # テーブル構造を確認
        c.execute("PRAGMA table_info(orders)")
        columns = [col[1] for col in c.fetchall()]
        app.logger.info(f"テーブル構造: {columns}")
        
        # ユーザーの注文履歴を取得
        c.execute('''
            SELECT item, quantity, created_at 
            FROM orders 
            WHERE line_user_id = ? 
            ORDER BY created_at DESC
        ''', (session['line_user_id'],))
        orders = [{'item': row[0], 'quantity': row[1], 'created_at': row[2]} for row in c.fetchall()]
        conn.close()
        
        app.logger.info(f"注文履歴を取得: {len(orders)}件")
        return render_template('mypage.html', 
                             user_name=session.get('line_user_name', 'ゲスト'),
                             orders=orders)
    except Exception as e:
        app.logger.error(f"マイページエラー: {str(e)}")
        return "エラーが発生しました。しばらく経ってから再度お試しください。", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
