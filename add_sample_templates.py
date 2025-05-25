#!/usr/bin/env python3
"""
サンプルテンプレートを追加するスクリプト
"""

import sqlite3
import os
from datetime import datetime

def get_db_path():
    """データベースパスを取得"""
    if os.path.exists('/opt/render'):
        return '/opt/render/project/.render-data/orders.db'
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orders.db')

def add_sample_templates():
    """サンプルテンプレートを追加"""
    db_path = get_db_path()
    print(f"データベースパス: {db_path}")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 既存のテンプレート数を確認
    c.execute('SELECT COUNT(*) FROM message_templates')
    existing_count = c.fetchone()[0]
    
    if existing_count > 0:
        print(f"既に{existing_count}個のテンプレートが存在します。")
        response = input("サンプルテンプレートを追加しますか？ (y/N): ")
        if response.lower() != 'y':
            print("キャンセルしました。")
            conn.close()
            return
    
    # サンプルテンプレートデータ
    sample_templates = [
        # 注文フォーム関連
        {
            'folder_name': '注文フォーム関連',
            'name': 'ご注文受付完了のお知らせ',
            'type': 'text',
            'content': 'この度はご注文いただき、誠にありがとうございます。\n\nご注文内容を確認させていただき、製作に入らせていただきます。\n\n製作期間は約2週間程度となります。\n完成次第、改めてご連絡いたします。\n\nご不明な点がございましたら、お気軽にお問い合わせください。',
        },
        {
            'folder_name': '注文フォーム関連',
            'name': '製作開始のご連絡',
            'type': 'text',
            'content': 'お世話になっております。\n\nご注文いただきました商品の製作を開始いたします。\n\n完成予定日：{完成予定日}\n\n製作状況につきましては、随時ご報告させていただきます。\n今しばらくお待ちください。',
        },
        
        # 発送連絡
        {
            'folder_name': '発送連絡',
            'name': '商品発送完了のお知らせ',
            'type': 'text',
            'content': 'お世話になっております。\n\nご注文いただきました商品の発送が完了いたしました。\n\n【配送情報】\n配送業者：ヤマト運輸\n追跡番号：{追跡番号}\n\nお届け予定日：{お届け予定日}\n\n商品到着までもうしばらくお待ちください。',
        },
        
        # 画像送信
        {
            'folder_name': '画像送信',
            'name': 'デザイン確認依頼',
            'type': 'image',
            'content': 'https://example.com/design-sample.jpg',
        },
        {
            'folder_name': '画像送信',
            'name': 'サイズ表',
            'type': 'image',
            'content': 'https://example.com/size-chart.jpg',
        },
        
        # Fテンプレ（フレックスメッセージ）
        {
            'folder_name': 'Fテンプレ',
            'name': '商品カタログ',
            'type': 'flex',
            'content': '''
{
  "type": "flex",
  "altText": "商品カタログ",
  "contents": {
    "type": "bubble",
    "hero": {
      "type": "image",
      "url": "https://example.com/product-catalog.jpg",
      "size": "full",
      "aspectRatio": "20:13",
      "aspectMode": "cover"
    },
    "body": {
      "type": "box",
      "layout": "vertical",
      "contents": [
        {
          "type": "text",
          "text": "2025年新商品カタログ",
          "weight": "bold",
          "size": "xl"
        },
        {
          "type": "text",
          "text": "最新のスポーツウェアをご覧ください",
          "size": "md",
          "color": "#666666",
          "margin": "md"
        }
      ]
    },
    "footer": {
      "type": "box",
      "layout": "vertical",
      "contents": [
        {
          "type": "button",
          "style": "primary",
          "action": {
            "type": "uri",
            "label": "詳細を見る",
            "uri": "https://example.com/catalog"
          }
        }
      ]
    }
  }
}
            '''.strip(),
        },
        
        # イラレ担当
        {
            'folder_name': 'イラレ担当',
            'name': 'デザイン修正依頼',
            'type': 'text',
            'content': 'デザインの修正をお願いいたします。\n\n【修正内容】\n・文字サイズを大きく\n・色を青系に変更\n・ロゴの位置を右上に\n\n修正完了後、確認用の画像をお送りください。\nよろしくお願いいたします。',
        },
        
        # いい感じ画像
        {
            'folder_name': 'いい感じ画像',
            'name': 'イメージ画像送信',
            'type': 'image',
            'content': 'https://example.com/nice-image.jpg',
        },
        
        # バスケ
        {
            'folder_name': 'バスケ',
            'name': 'バスケットボールユニフォーム見積もり',
            'type': 'text',
            'content': 'バスケットボールユニフォームのお見積もりです。\n\n【商品詳細】\n・リバーシブルユニフォーム\n・サイズ：S〜XL\n・数量：15着\n・納期：2週間\n\n単価：¥8,800（税込）\n合計：¥132,000（税込）\n\nご不明点がございましたらお気軽にお尋ねください。',
        },
        
        # ホッケー
        {
            'folder_name': 'ホッケー',
            'name': 'ホッケーユニフォーム仕様書',
            'type': 'text',
            'content': 'ホッケーユニフォームの仕様についてご案内いたします。\n\n【仕様】\n・素材：吸汗速乾ポリエステル\n・袖：半袖/長袖選択可\n・プリント：昇華プリント\n・オプション：ネーム・ナンバー\n\n詳細な仕様書をお送りいたします。\nご確認ください。',
        }
    ]
    
    # フォルダIDを取得してテンプレートを挿入
    for template_data in sample_templates:
        folder_name = template_data['folder_name']
        
        # フォルダIDを取得
        c.execute('SELECT id FROM template_folders WHERE name = ?', (folder_name,))
        folder_result = c.fetchone()
        
        if not folder_result:
            print(f"警告: フォルダ '{folder_name}' が見つかりません。スキップします。")
            continue
            
        folder_id = folder_result[0]
        
        # プレビューテキストを生成
        content = template_data['content']
        template_type = template_data['type']
        
        if template_type == 'text':
            preview_text = content[:100] + ('...' if len(content) > 100 else '')
        elif template_type == 'image':
            preview_text = f"画像: {content}"
        elif template_type == 'video':
            preview_text = f"動画: {content}"
        elif template_type in ['carousel', 'flex']:
            preview_text = f"{template_type.capitalize()}メッセージ"
        else:
            preview_text = content[:50] + ('...' if len(content) > 50 else '')
        
        # 最大ソート順を取得
        c.execute('SELECT MAX(sort_order) FROM message_templates WHERE folder_id = ?', (folder_id,))
        max_order_result = c.fetchone()
        max_order = (max_order_result[0] or 0) + 1
        
        # テンプレート挿入
        c.execute('''
            INSERT INTO message_templates (folder_id, name, type, content, preview_text, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (folder_id, template_data['name'], template_type, content, preview_text, max_order))
        
        print(f"✓ '{template_data['name']}' を '{folder_name}' フォルダに追加しました")
    
    conn.commit()
    conn.close()
    
    print(f"\n{len(sample_templates)}個のサンプルテンプレートを追加しました！")
    print("\n管理画面のテンプレートページでご確認ください：")
    print("http://localhost:5000/admin/templates")

if __name__ == '__main__':
    add_sample_templates() 