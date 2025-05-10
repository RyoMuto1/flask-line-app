from flask import Flask, render_template, request, redirect, jsonify, session
import sqlite3
import requests
import os
from dotenv import load_dotenv

# .envファイル読み込み
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # セッション暗号化キー

# ✅ LINEメッセージ送信関数
def send_line_message(user_id, message):
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    body = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': message}]
    }
    response = requests.post(url, headers=headers, json=body)
    print("🔁 LINE Push 結果:", response.status_code, response.text)

# データベース初期化
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

# ルート：フォーム表示＆注文処理
@app.route('/', methods=['GET', 'POST'])
def order_form():
    if request.method == 'POST':
        name = request.form['name']
        item = request.form['item']
        quantity = int(request.form['quantity'])

        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute(
            'INSERT INTO orders (name, item, quantity) VALUES (?, ?, ?)',
            (name, item, quantity)
        )
        conn.commit()
        conn.close()

        send_line_message(
            user_id='Uf7eaddb8bba99098330d4d6ff1c2e5e0',  # 動的対応可
            message=f'{name}さん、ご注文ありがとうございました！「{item}」を{quantity}個承りました😊'
        )
        return redirect('/thanks')

    return render_template('form.html')

@app.route('/thanks')
def thanks():
    return 'ご注文ありがとうございました！'

@app.route('/history')
def history():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute('SELECT * FROM orders')
    rows = c.fetchall()
    conn.close()

    output = '<h2>注文履歴</h2><ul>'
    for row in rows:
        output += f'<li>{row[1]}さんが「{row[2]}」を{row[3]}個注文</li>'
    output += '</ul>'
    return output

# Webhook（LINE Bot用）
@app.route('/webhook', methods=['POST'])
def webhook():
    print("📬 webhook hit!", request.json)
    return jsonify({'status': 'ok'}), 200

# LINEログイン設定
LINE_LOGIN_CHANNEL_ID = os.environ.get("LINE_LOGIN_CHANNEL_ID")
LINE_LOGIN_CHANNEL_SECRET = os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
LINE_REDIRECT_URI = "https://flask-line-app-essd.onrender.com/callback"

@app.route('/login')
def login():
    login_url = (
        "https://access.line.me/oauth2/v2.1/authorize"
        "?response_type=code"
        f"&client_id={LINE_LOGIN_CHANNEL_ID}"
        f"&redirect_uri={LINE_REDIRECT_URI}"
        "&scope=profile%20openid"
        "&state=12345abcde"
    )
    return redirect(login_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')

    # トークン取得
    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': LINE_REDIRECT_URI,
        'client_id': LINE_LOGIN_CHANNEL_ID,
        'client_secret': LINE_LOGIN_CHANNEL_SECRET,
    }
    resp = requests.post(token_url, headers=headers, data=data)
    token_data = resp.json()
    print("🐛 token_data:", token_data)

    id_token = token_data.get('id_token')
    if not id_token:
        return 'id_tokenが取得できませんでした', 500

    # プロファイル検証
    verify_url = "https://api.line.me/oauth2/v2.1/verify"
    params = {'id_token': id_token, 'client_id': LINE_LOGIN_CHANNEL_ID}
    vresp = requests.get(verify_url, params=params)
    profile = vresp.json()
    print("🐛 verify response:", profile)

    user_id = profile.get('sub')
    user_name = profile.get('name', '名無し')
    if not user_id:
        return 'ユーザーIDが取得できませんでした', 500

    # セッション保存
    session['line_user_id'] = user_id
    session['line_user_name'] = user_name

    return (
        f"<h2>ログイン成功！</h2>"
        f"<p>こんにちは、{user_name}さん！</p>"
        f"<a href='/'>フォームに戻る</a>"
    )

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=10000)
