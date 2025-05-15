#!/bin/bash

# データベースの初期化
python init_db.py

# 管理者アカウントの作成（環境変数から取得）
python create_admin.py --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD"

# アプリケーションの起動
gunicorn app:app 