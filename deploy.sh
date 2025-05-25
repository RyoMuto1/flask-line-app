#!/bin/bash

# Renderへの一括デプロイスクリプト
# このスクリプトは1つのコマンドでGitへのpushとRenderでのデプロイを実行します

echo "🚀 Renderへのデプロイを開始します..."

# 1. 現在のステータスを確認
echo "📊 現在のGitステータスを確認中..."
git status

# 2. 変更をステージング
echo "📝 変更をステージングに追加中..."
git add .

# 3. コミットメッセージを作成（引数があれば使用、なければデフォルト）
if [ -n "$1" ]; then
    COMMIT_MESSAGE="$1"
else
    COMMIT_MESSAGE="テンプレート管理機能の実装完了 - $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo "💾 コミット中: $COMMIT_MESSAGE"
git commit -m "$COMMIT_MESSAGE"

# 4. mainブランチにpush
echo "⬆️  Renderにpush中..."
git push origin main

# 5. デプロイ完了メッセージ
echo ""
echo "✅ デプロイが完了しました！"
echo ""
echo "🌐 本番環境での確認:"
echo "   - アプリケーション: https://your-render-app.onrender.com"
echo "   - 管理画面: https://your-render-app.onrender.com/admin/login"
echo "   - テンプレート管理: https://your-render-app.onrender.com/admin/templates"
echo ""
echo "📱 実装された機能:"
echo "   ✅ テンプレート管理画面"
echo "   ✅ フォルダによる分類機能"
echo "   ✅ テキスト・画像・動画・カルーセル・フレックスメッセージ対応"
echo "   ✅ テンプレートの作成・編集・削除機能"
echo "   ✅ 検索・フィルタリング機能"
echo "   ✅ プレビュー機能"
echo "   ✅ レスポンシブ対応UI"
echo ""
echo "📋 次のステップ（推奨実装順序）:"
echo "   1. ✅ テンプレート管理機能 (完了)"
echo "   2. 🔄 一斉配信機能"
echo "   3. ⏰ リマインド配信機能"
echo "   4. 🎯 ステップ配信機能"
echo ""
echo "🎉 テンプレート管理機能の実装が完了しました！" 