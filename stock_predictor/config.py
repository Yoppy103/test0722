"""設定。config.toml（任意）で上書きできる。"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path


@dataclass
class XConfig:
    bearer_token: str = ""  # 環境変数 X_BEARER_TOKEN でも可
    min_followers: int = 10_000
    lookback_days: int = 7
    max_pages: int = 10  # 1ページ最大100件
    lang: str = "ja"
    # 検索クエリ（recent search）。$ キャッシュタグ演算子は Basic 以上のプランが必要。
    query: str = "(銘柄 OR 株 OR 決算 OR 上方修正 OR ストップ高 OR 爆上げ OR 買い増し) -is:retweet"
    # 監視アカウントを固定する場合はユーザー名を列挙（空なら検索モード）
    accounts: list = field(default_factory=list)


@dataclass
class ScoringConfig:
    market: str = "jp"  # jp / us / both
    weight_social: float = 0.5
    weight_technical: float = 0.3
    weight_fundamental: float = 0.2
    recency_half_life_days: float = 2.0
    attention_base: float = 0.15  # 感情語のない言及も「注目」として僅かに加点
    social_scale_floor: float = 1.0  # SNSスコア正規化スケールの下限（話題が少ない週に過大評価しない）
    min_unique_authors: int = 2  # 単独アカウントの煽りを除外
    min_score: float = 55.0
    top_n: int = 5


@dataclass
class TradingConfig:
    initial_capital: float = 3_000_000
    lot_size: int = 100  # 日本株は単元100株、米国株は1
    commission_rate: float = 0.0  # 片道手数料率（例: 0.00055）
    slippage_bps: float = 10.0  # 成行の滑り（買いは不利方向）
    # 売却ルール
    stop_atr_mult: float = 1.5
    min_stop_pct: float = 0.03
    max_stop_pct: float = 0.08
    take_profit_atr_mult: float = 3.0
    min_take_profit_pct: float = 0.05
    trail_activate_pct: float = 0.04
    trail_pct: float = 0.03
    rsi_exit: float = 78.0
    momentum_exit: bool = True
    avoid_earnings: bool = True
    # シグナル売りの約定: next_open（翌営業日寄り成行。引け値を見てから発注する現実的な想定）/ close（当日引け、楽観的）
    signal_execution: str = "next_open"


@dataclass
class MarketDataConfig:
    provider: str = "yfinance"  # yfinance / csv / synthetic
    csv_dir: str = "stock_predictor/data/prices"
    benchmark: str = "^N225"


@dataclass
class Config:
    db_path: str = "stock_predictor/data/stock_predictor.db"
    timezone: str = "Asia/Tokyo"
    x: XConfig = field(default_factory=XConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)


def _apply(obj, values: dict):
    for f in fields(obj):
        if f.name not in values:
            continue
        cur = getattr(obj, f.name)
        if is_dataclass(cur):
            _apply(cur, values[f.name])
        else:
            setattr(obj, f.name, values[f.name])


def load_config(path: str | None = None) -> Config:
    cfg = Config()
    path = path or os.environ.get("STOCK_PREDICTOR_CONFIG", "stock_predictor/config.toml")
    if path and Path(path).exists():
        with open(path, "rb") as fp:
            _apply(cfg, tomllib.load(fp))
    if not cfg.x.bearer_token:
        cfg.x.bearer_token = os.environ.get("X_BEARER_TOKEN", "")
    return cfg
