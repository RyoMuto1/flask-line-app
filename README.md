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
- **Frontend**: HTML/CSS/JavaScript (独立CSS設計)
- **Deploy**: Render
- **Real-time**: Socket.IO
- **LINE API**: Messaging API

## 🎨 フロントエンド設計思想

### CSS完全独立化アーキテクチャ
本システムでは、**ページごとのCSS完全独立**を実現しています。Bootstrap依存から脱却し、保守性と拡張性を大幅に向上させました。

```
📁 static/css/
├── 📁 base/                    # 共通レイアウト
│   ├── base.css                # サイドバー等の基本構造
│   └── variables.css           # 共通変数
├── auth-login.css              # ログインページ
├── auth-reset.css              # パスワードリセット
├── auth-first-admin.css        # 初回管理者作成
├── settings-password.css       # パスワード変更
├── settings-profile.css        # プロフィール編集
├── dashboard.css               # ダッシュボード
├── tags.css                    # タグ管理
├── analytics-*.css             # 流入経路分析
├── chat.css                    # チャット機能
└── [feature].css               # その他機能
```

### プレフィックス命名規則

| カテゴリ | プレフィックス | 例 | 対象ページ |
|---------|----------------|----|---------| 
| **認証系** | `auth__` | `.auth__login-btn` | ログイン、パスワードリセット等 |
| **設定系** | `settings__` | `.settings__form-control` | パスワード変更、プロフィール等 |
| **管理機能** | `[feature]__` | `.tags__sidebar-item` | タグ管理、流入分析等 |
| **詳細画面** | `[detail]__` | `.orderdetail__info-card` | 注文詳細、ユーザー詳細等 |
| **チャット** | `chat__` | `.chat__message-box` | チャット関連画面 |

### 新規ページ作成ガイドライン

#### 1. CSSファイル作成
```bash
# 新機能「analytics」の場合
touch static/css/analytics.css
```

#### 2. CSS構造テンプレート
```css
/* [機能名]ページ専用スタイル - 完全独立版 */

/* =================================
   基本レイアウト
   ================================= */
.analytics__page-container {
    margin-left: 250px; /* base.cssのサイドバー幅に合わせる */
    padding: 2rem;
    background-color: #f8f9fa;
    min-height: 100vh;
}

/* =================================
   Bootstrap代替クラス - ボタン
   ================================= */
.analytics__btn {
    display: inline-block;
    font-weight: 400;
    /* ... Bootstrap代替スタイル ... */
}

.analytics__btn-primary {
    color: #fff;
    background-color: #007bff;
    border-color: #007bff;
}

/* =================================
   機能固有のスタイル
   ================================= */
.analytics__unique-feature {
    /* ここに機能固有のスタイルを記述 */
}

/* =================================
   レスポンシブ対応
   ================================= */
@media (max-width: 768px) {
    .analytics__page-container {
        margin-left: 0;
        padding: 1rem;
    }
}
```

#### 3. HTMLテンプレート構造
```html
{% extends 'admin/base.html' %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/analytics.css') }}">
{% endblock %}

{% block content %}
<div class="analytics__page-container">
    <h1 class="analytics__page-title">機能名</h1>
    
    <!-- プレフィックス付きクラスを使用 -->
    <div class="analytics__content">
        <button class="analytics__btn analytics__btn-primary">
            ボタン
        </button>
    </div>
</div>
{% endblock %}
```

#### 4. 必須チェックリスト

- [ ] プレフィックスが全クラスに適用されている
- [ ] Bootstrap系クラス（`btn`, `card`, `container`等）を使用していない
- [ ] `{% block extra_css %}`でCSSを読み込んでいる
- [ ] レスポンシブ対応済み（768px, 576px breakpoints）
- [ ] base.cssのサイドバー幅（250px）に対応したレイアウト

### ページ分類と独立化状況

#### ✅ 完全独立化済み（管理者ページ）

| ページ | プレフィックス | CSSファイル |
|--------|---------------|------------|
| ログイン | `auth__` | `auth-login.css` |
| パスワードリセット | `auth__` | `auth-reset.css` |
| 初回管理者作成 | `auth__` | `auth-first-admin.css` |
| パスワード変更 | `settings__` | `settings-password.css` |
| プロフィール編集 | `settings__` | `settings-profile.css` |
| ダッシュボード | `dashboard__` | `dashboard.css` |
| タグ管理 | `tags__` | `tags.css` |
| 流入経路分析 | `analytics__` | `line-source-analytics.css` |
| 対応マーク管理 | `statusmarks__` | `status-markers.css` |
| チャット管理 | `chat__` | `chat.css` |
| 注文詳細 | `orderdetail__` | `order-detail.css` |
| ユーザー詳細 | `userdetail__` | `user-detail.css` |
| 管理者一覧 | `adminlist__` | `admin-list.css` |
| 流入ユーザー詳細 | `analyticsusers__` | `analytics-users.css` |

#### ⚠️ Bootstrap依存（一般ユーザーページ）

| ページ | 状況 | 備考 |
|--------|------|------|
| 注文フォーム | Bootstrap使用 | 将来的な独立化候補 |
| 注文完了 | Bootstrap使用 | 将来的な独立化候補 |
| マイページ | Bootstrap使用 | 将来的な独立化候補 |

### 設計上の利点

1. **保守性向上**: ページごとに独立してスタイリング可能
2. **パフォーマンス**: 不要なCSSの読み込みなし
3. **開発効率**: 他ページへの影響を気にせず修正可能
4. **一貫性**: プレフィックス方式による統一された命名規則
5. **拡張性**: 新機能追加時の設計が明確

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
- [x] **管理者ページ完全独立化**

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

4. **一般ユーザーページ独立化**
   - `user__` プレフィックス採用
   - 統一されたデザインシステム

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
