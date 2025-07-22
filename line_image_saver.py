#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LINEで送られた画像を保存するPythonスクリプト
"""

import os
import requests
import json
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage

# 設定ファイルをインポート
from config import CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET, SAVE_DIR, FLASK_HOST, FLASK_PORT, FLASK_DEBUG

# LINE APIクライアント初期化
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Flaskアプリケーション初期化
app = Flask(__name__)

def ensure_save_directory():
    """保存ディレクトリが存在しない場合は作成"""
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
        print(f"保存ディレクトリ '{SAVE_DIR}' を作成しました")

def save_image(message_id, user_id):
    """画像を保存する関数"""
    try:
        # 画像のコンテンツを取得
        message_content = line_bot_api.get_message_content(message_id)
        
        # ファイル名を生成（タイムスタンプ + ユーザーID + メッセージID）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{user_id}_{message_id}.jpg"
        filepath = os.path.join(SAVE_DIR, filename)
        
        # 画像を保存
        with open(filepath, 'wb') as fd:
            for chunk in message_content.iter_content():
                fd.write(chunk)
        
        print(f"画像を保存しました: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"画像の保存中にエラーが発生しました: {e}")
        return None

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhookからのコールバックを処理"""
    # リクエストヘッダーからX-Line-Signatureを取得
    signature = request.headers['X-Line-Signature']

    # リクエストボディを取得
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        # 署名を検証し、問題なければhandleに定義されている関数を呼び出す
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 署名検証で失敗したときは例外をあげる
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    """画像メッセージを処理"""
    print(f"画像メッセージを受信しました: {event.message.id}")
    print(f"送信者ID: {event.source.user_id}")
    
    # 保存ディレクトリを確認
    ensure_save_directory()
    
    # 画像を保存
    saved_path = save_image(event.message.id, event.source.user_id)
    
    if saved_path:
        # 保存成功のメッセージを送信
        from linebot.models import TextSendMessage
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"画像を保存しました: {os.path.basename(saved_path)}")
        )
    else:
        # 保存失敗のメッセージを送信
        from linebot.models import TextSendMessage
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="画像の保存に失敗しました。")
        )

def main():
    """メイン関数"""
    print("LINE画像保存スクリプトを開始します...")
    print("保存ディレクトリを確認中...")
    ensure_save_directory()
    
    # Flaskアプリケーションを起動
    # 本番環境では適切なWSGIサーバーを使用してください
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

if __name__ == "__main__":
    main() 