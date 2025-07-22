#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LINEで送られた画像を保存し、OCRで文字起こしするPythonスクリプト
"""

import os
import requests
import json
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage
from google.cloud import vision

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

def ocr_image(image_path):
    """画像をOCRで文字起こしする関数"""
    try:
        # Vision APIクライアントを初期化
        client = vision.ImageAnnotatorClient()
        
        # 画像ファイルを読み込み
        with open(image_path, "rb") as image_file:
            content = image_file.read()
        
        # Vision APIに送信する画像オブジェクトを作成
        image = vision.Image(content=content)
        
        # テキスト検出を実行
        response = client.text_detection(image=image)
        texts = response.text_annotations
        
        if texts:
            # 最初の結果が全文を含む
            ocr_text = texts[0].description
            print(f"OCR結果: {ocr_text}")
            return ocr_text
        else:
            print("テキストが検出されませんでした")
            return "テキストが検出されませんでした"
            
    except Exception as e:
        print(f"OCR処理中にエラーが発生しました: {e}")
        return f"OCR処理エラー: {str(e)}"

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
        # OCR処理を実行
        ocr_result = ocr_image(saved_path)
        
        # 結果をLINEに返信
        from linebot.models import TextSendMessage
        reply_message = f"画像を保存しました: {os.path.basename(saved_path)}\n\n文字起こし結果:\n{ocr_result}"
        
        # メッセージが長すぎる場合は分割
        if len(reply_message) > 5000:
            reply_message = f"画像を保存しました: {os.path.basename(saved_path)}\n\n文字起こし結果（長いため省略）:\n{ocr_result[:4000]}..."
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_message)
        )
    else:
        # 保存失敗のメッセージを送信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="画像の保存に失敗しました。")
        )

def main():
    """メイン関数"""
    print("LINE画像保存・OCRスクリプトを開始します...")
    print("保存ディレクトリを確認中...")
    ensure_save_directory()
    
    # Google Cloud Vision APIの認証確認
    try:
        # テスト用のクライアントを作成して認証を確認
        client = vision.ImageAnnotatorClient()
        print("Google Cloud Vision APIの認証が正常です")
    except Exception as e:
        print(f"Google Cloud Vision APIの認証エラー: {e}")
        print("GOOGLE_APPLICATION_CREDENTIALS環境変数を設定してください")
        return
    
    # Flaskアプリケーションを起動
    # 本番環境では適切なWSGIサーバーを使用してください
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)

if __name__ == "__main__":
    main() 