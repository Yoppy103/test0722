#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設定ファイルのサンプル
このファイルをconfig.pyにコピーして、実際の値を設定してください
"""

import os

# LINE API設定
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

# 設定の検証
if CHANNEL_ACCESS_TOKEN == 'YOUR_CHANNEL_ACCESS_TOKEN':
    print("警告: LINE_CHANNEL_ACCESS_TOKENが設定されていません")
if CHANNEL_SECRET == 'YOUR_CHANNEL_SECRET':
    print("警告: LINE_CHANNEL_SECRETが設定されていません")

# 保存先ディレクトリ
SAVE_DIR = os.getenv('SAVE_DIR', 'saved_images')

# Flask設定
FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

# ログ設定
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO') 