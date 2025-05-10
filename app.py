from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
import requests
import os
from dotenv import load_dotenv

load_dotenv()  # ← .envファイルを読み込む

app = Flask(__name__)

# ✅ LINEメッセージ送信関数
def send_line_message(user_id, message):
    access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
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

@app.route('/', methods=['GET', 'POST'])
def order_form():
    if request.method == 'POST':
        name = request.form['name']
        item = request.form['item']
        quantity = int(request.form['quantity'])

        conn = sqlite3.connect('orders.db')
        c = conn.cursor()
        c.execute('INSERT INTO orders (name, item, quantity) VALUES (?, ?, ?)', (name, item, quantity))
        conn.commit()
        conn.close()

        # ✅ フォーム送信後にLINEへ自動メッセージ送信
        send_line_message(
            user_id='Uf7eaddb8bba99098330d4d6ff1c2e5e0',  # ← 必要ならここを動的に
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

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        body = request.get_json(force=True)
        print("📩 Webhook受信内容：", body)

        events = body.get("events", [])
        for event in events:
            print("🔍 イベント詳細：", event)
            if event.get("type") == "message":
                user_id = event["source"]["userId"]
                print(f"✅ 送信者のuserId: {user_id}")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        import traceback
        print("⚠️ エラー：", e)
        traceback.print_exc()  # ← これを入れるとエラー詳細がログに出ます
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    init_db()
    app.run(host="0.0.0.0", port=10000)
