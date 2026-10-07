"""株価・ファンダメンタルデータの取得。プロバイダを差し替え可能。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import zlib

import numpy as np
import pandas as pd

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class MarketDataProvider:
    def daily(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """[start, end] の日足。index は date（昇順）、列は COLUMNS。"""
        raise NotImplementedError

    def fundamentals(self, ticker: str) -> dict:
        """per, pbr, roe, revenue_growth, next_earnings(date) など。取得できない項目は省略。"""
        return {}


class YFinanceProvider(MarketDataProvider):
    def __init__(self):
        import yfinance  # noqa: F401  遅延 import（未インストールでも他プロバイダは動く）
        self._cache: dict[str, pd.DataFrame] = {}

    def daily(self, ticker, start, end):
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end + timedelta(days=1), interval="1d",
                         progress=False, auto_adjust=False)
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[COLUMNS].dropna()
        df.index = pd.to_datetime(df.index).date
        return df

    def fundamentals(self, ticker):
        import yfinance as yf
        t = yf.Ticker(ticker)
        out = {}
        try:
            info = t.info or {}
            out = {
                "per": info.get("trailingPE") or info.get("forwardPE"),
                "pbr": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "revenue_growth": info.get("revenueGrowth"),
                "market_cap": info.get("marketCap"),
            }
        except Exception:
            pass
        try:
            cal = t.calendar or {}
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if dates:
                out["next_earnings"] = pd.Timestamp(dates[0]).date()
        except Exception:
            pass
        return {k: v for k, v in out.items() if v is not None}


class CsvProvider(MarketDataProvider):
    """<dir>/<ticker>.csv（Date,Open,High,Low,Close,Volume）と任意の fundamentals.csv を読む。"""

    def __init__(self, directory: str):
        self.dir = Path(directory)

    def daily(self, ticker, start, end):
        path = self.dir / f"{ticker}.csv"
        if not path.exists():
            return pd.DataFrame(columns=COLUMNS)
        df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
        df.index = df.index.date
        return df.loc[(df.index >= start) & (df.index <= end), COLUMNS]

    def fundamentals(self, ticker):
        path = self.dir / "fundamentals.csv"
        if not path.exists():
            return {}
        df = pd.read_csv(path, dtype={"ticker": str}).set_index("ticker")
        if ticker not in df.index:
            return {}
        row = df.loc[ticker].dropna().to_dict()
        if "next_earnings" in row:
            row["next_earnings"] = pd.Timestamp(row["next_earnings"]).date()
        return row


class SyntheticProvider(MarketDataProvider):
    """オフライン動作確認用の擬似株価（ティッカー名から決定的に生成）。

    drift_by_week で特定銘柄・週に上昇バイアスを与えられる（デモ用）。
    """

    def __init__(self, start: date = date(2025, 1, 1), end: date = date(2027, 12, 31),
                 drift_by_week: Optional[dict] = None, seed: int = 0):
        self.start, self.end, self.seed = start, end, seed
        self.drift_by_week = drift_by_week or {}
        self._cache: dict[str, pd.DataFrame] = {}

    def _series(self, ticker: str) -> pd.DataFrame:
        if ticker in self._cache:
            return self._cache[ticker]
        rng = np.random.default_rng(zlib.crc32(f"{ticker}|{self.seed}".encode()))
        days = pd.bdate_range(self.start, self.end)
        price = 500 + rng.random() * 4500
        rows = []
        for d in days:
            monday = (d - pd.Timedelta(days=d.weekday())).date()
            drift = self.drift_by_week.get((ticker, monday), 0.0)
            ret = rng.normal(drift, 0.018)
            o = price * (1 + rng.normal(0, 0.005))
            c = o * (1 + ret)
            h = max(o, c) * (1 + abs(rng.normal(0, 0.006)))
            l = min(o, c) * (1 - abs(rng.normal(0, 0.006)))
            rows.append((d.date(), o, h, l, c, int(rng.integers(1e5, 1e6))))
            price = c
        df = pd.DataFrame(rows, columns=["Date"] + COLUMNS).set_index("Date")
        self._cache[ticker] = df
        return df

    def daily(self, ticker, start, end):
        df = self._series(ticker)
        return df.loc[(df.index >= start) & (df.index <= end)]

    def fundamentals(self, ticker):
        rng = np.random.default_rng(zlib.crc32(f"{ticker}|f|{self.seed}".encode()))
        return {"per": float(rng.uniform(6, 40)), "pbr": float(rng.uniform(0.5, 5)),
                "roe": float(rng.uniform(-0.05, 0.25)), "revenue_growth": float(rng.uniform(-0.1, 0.3))}


def make_provider(cfg) -> MarketDataProvider:
    p = cfg.market_data.provider
    if p == "yfinance":
        return YFinanceProvider()
    if p == "csv":
        return CsvProvider(cfg.market_data.csv_dir)
    if p == "synthetic":
        return SyntheticProvider()
    raise ValueError(f"unknown provider: {p}")
