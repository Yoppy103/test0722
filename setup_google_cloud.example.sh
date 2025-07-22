#!/bin/bash

# Google Cloud Vision API設定
echo "Google Cloud Vision APIの設定を行います..."

# サービスアカウントキーファイルのパスを設定
# 実際のパスに変更してください
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"

echo "GOOGLE_APPLICATION_CREDENTIALS: $GOOGLE_APPLICATION_CREDENTIALS"

# ファイルが存在するかチェック
if [ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "✅ サービスアカウントキーファイルが見つかりました"
else
    echo "❌ サービスアカウントキーファイルが見つかりません"
    echo "以下の手順でサービスアカウントキーを作成してください："
    echo ""
    echo "1. Google Cloud Console (https://console.cloud.google.com/) にアクセス"
    echo "2. プロジェクトを選択または作成"
    echo "3. 'IAM と管理' > 'サービスアカウント' に移動"
    echo "4. 'サービスアカウントを作成' をクリック"
    echo "5. 名前を入力（例：line-ocr-bot）"
    echo "6. 'キーを作成' > 'JSON' を選択"
    echo "7. ダウンロードしたJSONファイルのパスをこのスクリプトに設定"
    echo ""
    echo "また、以下のAPIを有効化してください："
    echo "- Cloud Vision API"
    echo ""
    echo "サービスアカウントには以下の権限が必要です："
    echo "- Cloud Vision API User"
fi 