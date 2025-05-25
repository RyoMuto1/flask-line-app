# Flask Order Form - LINE拡張システム

## 🚀 概要
スポーツウェア注文管理システムにLINE拡張機能を追加したアプリケーションです。

## ✨ 主な機能

### 📝 基本機能
- 注文フォーム（複数商品対応）
- ユーザー管理・認証
- LINE Bot連携
- リアルタイムチャット機能
- 管理者画面

### 🏷️ タグ・ステータス管理
- ユーザータグ機能
- 対応ステータスマーカー
- 流入経路分析

### 📄 **テンプレート管理機能（新機能）**
- **フォルダによる分類管理**
  - カラーコード付きフォルダ
  - ドラッグ&ドロップ並び替え
  - 階層構造対応

- **多様なメッセージタイプ**
  - 📝 テキストメッセージ
  - 🖼️ 画像メッセージ  
  - 🎬 動画メッセージ
  - 🎠 カルーセルメッセージ
  - 📊 フレックスメッセージ

- **高度な管理機能**
  - リアルタイム検索・フィルタリング
  - 一括選択・削除
  - プレビュー機能
  - レスポンシブ対応UI

### 🎯 計画中の配信機能
1. **一斉配信** - タグで絞り込み、指定時間に配信
2. **ステップ配信** - アクションをトリガーに段階的配信  
3. **リマインド配信** - ゴール日時に向けた自動リマインド

## 🛠️ 技術スタック
- **Backend**: Python Flask
- **Database**: SQLite
- **Frontend**: HTML/CSS/JavaScript (Bootstrap)
- **Deploy**: Render
- **Real-time**: Socket.IO
- **LINE API**: Messaging API

## 📦 デプロイメント

### 一括デプロイ（推奨）
```bash
./deploy.sh "コミットメッセージ"
```

### 手動デプロイ
```bash
git add .
git commit -m "update"
git push origin main
```

## 🎨 画面構成

### 管理画面
- `/admin/templates` - **テンプレート管理画面**
- `/admin/chat` - チャット管理
- `/admin/tags` - タグ管理  
- `/admin/status-markers` - ステータス管理
- `/admin/line-source-analytics` - 流入分析

### ユーザー画面
- `/` - 注文フォーム
- `/mypage` - マイページ
- `/chat` - チャット機能

## 🏗️ データベース構造

### テンプレート関連テーブル
```sql
-- フォルダ管理
template_folders (id, name, color, sort_order, created_at)

-- テンプレート管理  
message_templates (id, folder_id, name, type, content, preview_text, sort_order, created_at, updated_at)
```

## 🚀 開発ロードマップ

### ✅ 完了済み
- [x] テンプレート管理システム
- [x] フォルダ分類機能
- [x] 多様なメッセージタイプサポート
- [x] 検索・フィルタリング機能

### 🔄 次のステップ
1. **一斉配信機能** 
   - タグ絞り込み配信
   - 予約配信機能
   
2. **リマインド配信**
   - 日時指定自動配信
   - 繰り返し配信設定
   
3. **ステップ配信**
   - トリガーベース配信
   - 条件分岐フロー

## 📱 使用方法

### テンプレート管理
1. 管理画面ログイン: `/admin/login`
2. テンプレート管理: `/admin/templates`
3. 新しいフォルダ作成または既存フォルダ選択
4. テンプレート作成・編集・削除

### サンプルデータ追加
```bash
python add_sample_templates.py
```

## 🔧 開発者向け情報

### 環境構築
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python init_db.py
python app.py
```

### 主要エンドポイント
```python
# テンプレート管理
GET  /admin/templates                     # 一覧表示
POST /admin/templates/create              # 作成
POST /admin/templates/delete              # 削除
POST /admin/templates/folders/create      # フォルダ作成
```

---

## 🎯 テンプレート管理機能の設計思想

この機能は「レシピブック」のような考え方で設計されています：

- **フォルダ = 料理のジャンル** (和食、洋食、中華など)
- **テンプレート = レシピ** (具体的な料理の作り方)
- **タイプ = 調理法** (茹でる、焼く、揚げるなど)

これにより、他の配信機能すべてが**共通のテンプレートシステム**を利用できる基盤となっています。
