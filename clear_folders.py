#!/usr/bin/env python3
"""
既存のフォルダとテンプレートを削除するスクリプト
"""

import sqlite3
import os

def get_db_path():
    """データベースパスを取得"""
    if os.path.exists('/opt/render'):
        return '/opt/render/project/.render-data/orders.db'
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')

def clear_folders():
    """既存のフォルダとテンプレートを削除"""
    db_path = get_db_path()
    print(f"データベースパス: {db_path}")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 既存のテンプレートとフォルダを削除
    c.execute('DELETE FROM message_templates')
    print("✅ 既存のテンプレートを削除しました")
    
    c.execute('DELETE FROM template_folders')
    print("✅ 既存のフォルダを削除しました")
    
    conn.commit()
    conn.close()
    
    print("\n🎉 データベースクリア完了！")
    print("管理画面から新しいフォルダを作成してください。")

if __name__ == '__main__':
    clear_folders() 