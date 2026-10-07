# LINE画像保存・OCRスクリプト

> 同梱ツール: X投稿から来週上がりそうな株をスコアリングし仮想売買で検証する [stock_predictor](stock_predictor/README.md)

LINEで送られた画像を自動的に保存し、Google Cloud Vision APIで文字起こし（OCR）するPythonスクリプトです。

## 機能

- LINEで送られた画像を自動的に保存
- 保存した画像にタイムスタンプとユーザーIDを含むファイル名を付与
- Google Cloud Vision APIを使用したOCR（文字起こし）処理
- OCR結果をLINEで返信
- 保存成功時にLINEで確認メッセージを送信

## セットアップ手順

### 1. 必要なパッケージをインストール

```bash
pip install -r requirements.txt
```

### 2. Google Cloud Vision APIの設定

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. プロジェクトを選択または作成
3. Cloud Vision APIを有効化
4. サービスアカウントを作成し、キー（JSON）をダウンロード
5. `setup_google_cloud.sh`を編集して、ダウンロードしたJSONファイルのパスを設定
6. 認証設定を実行：
   ```bash
   source setup_google_cloud.sh
   ```

### 3. LINE Developers Consoleでチャンネルを作成

1. [LINE Developers Console](https://developers.line.biz/) にアクセス
2. 新しいチャンネルを作成（Messaging API）
3. チャンネルアクセストークンとチャンネルシークレットを取得

### 4. スクリプトの設定

1. 設定ファイルをコピーして設定：
   ```bash
   cp config.example.py config.py
   cp setup_env.example.sh setup_env.sh
   cp setup_google_cloud.example.sh setup_google_cloud.sh
   ```

2. `config.py` ファイルを編集して、実際の値を設定：
   ```python
   CHANNEL_ACCESS_TOKEN = 'YOUR_CHANNEL_ACCESS_TOKEN'  # あなたのチャンネルアクセストークン
   CHANNEL_SECRET = 'YOUR_CHANNEL_SECRET'  # あなたのチャンネルシークレット
   ```

3. `setup_env.sh` ファイルを編集して、環境変数を設定：
   ```bash
   export LINE_CHANNEL_ACCESS_TOKEN="YOUR_CHANNEL_ACCESS_TOKEN"
   export LINE_CHANNEL_SECRET="YOUR_CHANNEL_SECRET"
   ```

4. `setup_google_cloud.sh` ファイルを編集して、Google Cloud認証ファイルのパスを設定：
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
   ```

### 5. Webhook URLの設定

1. LINE Developers ConsoleでWebhook URLを設定：
   - URL: `https://your-domain.com/callback`
   - またはローカルテスト用: `https://ngrok.io/your-tunnel/callback`

2. Webhookを有効化

### 6. スクリプトの実行

```bash
# 画像保存のみ
python line_image_saver.py

# 画像保存 + OCR機能
python line_image_ocr_saver.py
```

## 使用方法

### ローカル実行

1. スクリプトを実行すると、Flaskサーバーが起動します（ポート5001）
2. LINEでボットに画像を送信すると、自動的に保存されます
3. OCR機能付きの場合は、文字起こし結果もLINEで返信されます
4. 保存された画像は `saved_images` ディレクトリに保存されます
5. ファイル名形式: `YYYYMMDD_HHMMSS_ユーザーID_メッセージID.jpg`

### Herokuデプロイ

1. Heroku CLIをインストール
2. Herokuアプリケーションを作成
3. 環境変数を設定：
   ```bash
   heroku config:set LINE_CHANNEL_ACCESS_TOKEN="YOUR_CHANNEL_ACCESS_TOKEN"
   heroku config:set LINE_CHANNEL_SECRET="YOUR_CHANNEL_SECRET"
   heroku config:set GOOGLE_APPLICATION_CREDENTIALS='{"type": "service_account", ...}'
   ```
4. デプロイ：
   ```bash
   git push heroku main
   ```
5. LINE Developers ConsoleでWebhook URLを設定：
   - URL: `https://your-app-name.herokuapp.com/callback`

## ファイル構造

```
.
├── line_image_saver.py           # 画像保存のみのスクリプト
├── line_image_ocr_saver.py       # 画像保存 + OCR機能付きスクリプト
├── requirements.txt              # 依存関係
├── config.example.py             # 設定ファイルのサンプル
├── setup_env.example.sh          # 環境変数設定のサンプル
├── setup_google_cloud.example.sh # Google Cloud認証設定のサンプル
├── .gitignore                   # Git除外設定
├── README.md                    # このファイル
├── Procfile                     # Herokuデプロイ設定
├── runtime.txt                  # Pythonバージョン指定
├── app.json                     # Herokuアプリケーション設定
└── saved_images/                # 保存された画像（自動生成）
    └── .gitkeep                 # ディレクトリ保持用ファイル
```

## 注意事項

- 本番環境では適切なWSGIサーバー（Gunicorn等）を使用してください
- HTTPS通信が必要です（ngrok等を使用してローカルテスト可能）
- チャンネルアクセストークンとシークレットは安全に管理してください
- 保存される画像の容量に注意してください
- Google Cloud Vision APIの利用料金が発生します
- サービスアカウントキーは安全に管理してください

## トラブルシューティング

### よくある問題

1. **署名検証エラー**
   - チャンネルシークレットが正しく設定されているか確認

2. **画像が保存されない**
   - チャンネルアクセストークンが正しく設定されているか確認
   - 保存ディレクトリの権限を確認

3. **Webhookが受信されない**
   - Webhook URLが正しく設定されているか確認
   - HTTPS通信が有効になっているか確認

4. **OCR処理エラー**
   - Google Cloud Vision APIが有効化されているか確認
   - サービスアカウントキーが正しく設定されているか確認
   - `GOOGLE_APPLICATION_CREDENTIALS`環境変数が設定されているか確認

5. **認証エラー**
   - サービスアカウントに適切な権限が付与されているか確認
   - Cloud Vision API Userロールが付与されているか確認 