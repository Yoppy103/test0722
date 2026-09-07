"""全スクリプト共通の初期化。sys.path・.env・モック接続先の切り替え。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.config import env, load_dotenv  # noqa: E402
from common.timing import Recorder  # noqa: E402


def base_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--mock",
        metavar="URL",
        help="モックサーバのURL (例: http://127.0.0.1:8899)。"
        "指定するとスマレジ/Bカートの接続先を差し替える。",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="リクエストを逐次表示")
    p.add_argument(
        "--out",
        default=str(ROOT / "out"),
        help="計測結果・レポートの出力先ディレクトリ",
    )
    return p


def setup(args) -> tuple[Recorder, Path, Path]:
    """(recorder, out_dir, trace_path) を返す。"""
    load_dotenv(ROOT / ".env")
    if args.mock:
        # モック時は資格情報が不要なので、未設定でも落ちないようダミーを入れる。
        import os

        for key, value in {
            "SMAREGI_CONTRACT_ID": "mockcontract",
            "SMAREGI_CLIENT_ID": "mock",
            "SMAREGI_CLIENT_SECRET": "mock",
            "BCART_CLIENT_ID": "mock",
            "BCART_CLIENT_SECRET": "mock",
        }.items():
            os.environ.setdefault(key, value)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    return Recorder(), out_dir, out_dir / "api_trace.jsonl"


def smaregi_urls(mock: str | None) -> dict:
    """SmaregiClient に渡す接続先オーバーライド。"""
    if not mock:
        return {}
    contract = env("SMAREGI_CONTRACT_ID", "mockcontract")
    return {
        "base_url_override": f"{mock.rstrip('/')}/{contract}/pos",
        "token_url_override": f"{mock.rstrip('/')}/app/{contract}/token",
    }


def bcart_urls(mock: str | None) -> dict:
    if not mock:
        return {}
    return {
        "base_url_override": f"{mock.rstrip('/')}/v1",
        "token_url_override": f"{mock.rstrip('/')}/oauth/token",
    }


def heading(text: str) -> None:
    print(f"\n=== {text} ===")
