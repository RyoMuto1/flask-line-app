#!/bin/bash

# データベースの初期化（管理者アカウントも自動作成されます）
python init_db.py

# アプリケーションの起動（WebSocket対応）
gunicorn -k eventlet app:application 