import os
import sqlite3
import requests
from flask import Flask, render_template, request, redirect, jsonify, session, Response
from dotenv import load_dotenv

# 環境変数をロード
load_dotenv()

app = Flask(__name__)
# セッション用の鍵（本番では環境変数から取得）
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# LINE Messaging API Push
def send_line_message(user_id, message):
    access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    body = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': message}]
    }
    res = requests.post(url, headers=headers, json=body)
    app.logger.debug(f"LINE Push Response: {res.status_code} {res.text}")

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

@app.route('/', methods=['GET', 'POST'])
def order_form():
    if request.method == 'POST':
        name = request.form['name']
        item = request.form['item']
        quantity = int(request.form['quantity'])
        # 保存
        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute('INSERT INTO orders (name,item,quantity) VALUES (?,?,?)', (name, item, quantity))
        conn.commit()
        conn.close()
        # LINEへ送信（サンプル固定ID）
        send_line_message(
            user_id='Uf7eaddb8bba99098330d4d6ff1c2e5e0',
            message=f'{name}さん、ご注文ありがとう！「{item}」x{quantity} 了解😊'
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
    c.execute('SELECT name,item,quantity FROM orders')
    rows = c.fetchall()
    conn.close()
    html = '<h2>注文履歴</h2><ul>'
    for name,item,qty in rows:
        html += f'<li>{name} さんが「{item}」を {qty} 個</li>'
    html += '</ul>'
    return html

# LINEからのWebhook受信（疎通確認用）
@app.route('/webhook', methods=['POST'])
def webhook():
    app.logger.debug('📬 webhook hit: %s', request.get_data())
    return jsonify({'status':'ok'})

# LINE Login 設定
LINE_LOGIN_CHANNEL_ID     = os.environ.get('LINE_LOGIN_CHANNEL_ID')
LINE_LOGIN_CHANNEL_SECRET = os.environ.get('LINE_LOGIN_CHANNEL_SECRET')
LINE_REDIRECT_URI         = os.environ.get('LINE_REDIRECT_URI')  # .env に設定

@app.route('/login')
def login():
    params = {
        'response_type': 'code',
        'client_id': LINE_LOGIN_CHANNEL_ID,
        'redirect_uri': LINE_REDIRECT_URI,
        'scope': 'openid profile',
        'state': '12345abcde'
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
            'grant_type':    'authorization_code',
            'code':          code,
            'redirect_uri':  LINE_REDIRECT_URI,
            'client_id':     LINE_LOGIN_CHANNEL_ID,
            'client_secret': LINE_LOGIN_CHANNEL_SECRET
        }
    )
    token_data = token_res.json()
    app.logger.debug('🐛 token_data: %s', token_data)
    id_token = token_data.get('id_token')
    if not id_token:
        return Response('id_token が取得できませんでした', status=500)
    # 検証
    verify_res = requests.get(
        'https://api.line.me/oauth2/v2.1/verify',
        params={'id_token': id_token, 'client_id': LINE_LOGIN_CHANNEL_ID}
    )
    profile = verify_res.json()
    app.logger.debug('🐛 profile: %s', profile)
    user_id   = profile.get('sub')
    user_name = profile.get('name')
    if not user_id:
        return Response('ユーザーID(sub) が取得できませんでした', status=500)
    # セッション保存
    session['line_user_id']   = user_id
    session['line_user_name'] = user_name
    # 表示
    return f"""
        <h2>ログイン成功!</h2>
        <p>こんにちは、{user_name} さん</p>
        <p>あなたの USER_ID: {user_id}</p>
        <a href='/'>トップへ</a>
    """

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
