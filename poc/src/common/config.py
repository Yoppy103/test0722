"""設定の読み込み: .env と endpoints.yaml をまとめて扱う。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """依存を増やさないための最小限の .env ローダ。既存の環境変数は上書きしない。"""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_endpoints() -> dict[str, Any]:
    with (ROOT / "config" / "endpoints.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(key: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and not value:
        raise SystemExit(
            f"環境変数 {key} が未設定です。.env.example をコピーして .env を作成してください。"
        )
    return value or ""


def resolve(template: str, **kwargs: str) -> str:
    """'https://api.smaregi.dev/{contract_id}/pos' のようなテンプレートを埋める。"""
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", value)
    return template


def endpoint(cfg: dict, vendor: str, name: str) -> tuple[str, str, bool]:
    """(method, path, confirmed) を返す。"""
    spec = cfg[vendor]["endpoints"][name]
    return spec["method"], spec["path"], bool(spec.get("confirmed", False))
