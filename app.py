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
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            item TEXT,
            quantity INTEGER
        )
    ''')
    conn.commit()
    conn.close()

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

@app.route('/', methods=['GET', 'POST'])
def order_form():
    # LINEログインしていない場合はログインページへリダイレクト
    if not session.get('line_user_id'):
        return redirect('/login')

    if request.method == 'POST':
        name     = request.form['name']
        item     = request.form['item']
        quantity = int(request.form['quantity'])

        # DB に保存
        conn = sqlite3.connect('orders.db')
        c    = conn.cursor()
        c.execute(
            'INSERT INTO orders (name, item, quantity) VALUES (?, ?, ?)',
            (name, item, quantity)
        )
        conn.commit()
        conn.close()

        # LINE へお知らせ
        send_line_message(
            user_id=session['line_user_id'],
            message=f'{name}さん、ご注文ありがとう！「{item}」 x {quantity} 承りました😊'
        )

        return redirect('/thanks')

    return render_template('form.html')

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
    if 'line_user_id' not in session:
        return redirect('/login')
    
    # ユーザーの注文履歴を取得
    conn = sqlite3.connect('orders.db')
    c    = conn.cursor()
    c.execute('SELECT name,item,quantity FROM orders WHERE line_user_id = ?', (session['line_user_id'],))
    rows = c.fetchall()
    conn.close()
    
    return render_template('mypage.html', 
                         user_name=session.get('line_user_name', 'ゲスト'),
                         orders=rows)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
