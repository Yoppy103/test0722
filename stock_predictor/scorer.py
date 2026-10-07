"""銘柄スコアリング: SNS（X）シグナル × テクニカル × ファンダメンタル。"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd

from . import indicators as ind
from .extractor import TickerExtractor
from .market_data import MarketDataProvider
from .models import Post, TickerScore
from .sentiment import analyze


def author_weight(followers: int, min_followers: int) -> float:
    """1万人→1.0, 10万人→2.0, 100万人→3.0（対数でインフルエンサー偏重を抑える）。"""
    base = max(min_followers, 1)
    return 1.0 + max(0.0, math.log10(max(followers, base) / base))


def engagement_weight(p: Post) -> float:
    return min(3.0, 1.0 + math.log1p(p.likes + 2 * p.retweets + p.quotes) / 5)


def social_signals(posts: list[Post], as_of: datetime, extractor: TickerExtractor, cfg,
                   min_followers: int, credibility: dict[str, float] | None = None) -> dict[str, dict]:
    credibility = credibility or {}
    # (ticker, author) -> 寄与リスト
    contrib: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    sentiments: dict[str, list[tuple[float, float]]] = defaultdict(list)
    recent_vs_old: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    names: dict[str, str] = {}
    for p in posts:
        tickers = extractor.extract(p.text)
        if not tickers:
            continue
        sent = analyze(p.text)
        age_days = max(0.0, (as_of - p.created_at).total_seconds() / 86400)
        recency = 0.5 ** (age_days / cfg.recency_half_life_days)
        w = (author_weight(p.author.followers, min_followers) * credibility.get(p.author.id, 1.0)
             * engagement_weight(p) * recency / math.sqrt(len(tickers)))  # 銘柄羅列ポストは希釈
        signal = sent if sent != 0 else cfg.attention_base
        names[p.author.id] = p.author.username
        for t in tickers:
            contrib[t][p.author.id].append(w * signal)
            sentiments[t].append((w, sent))
            recent_vs_old[t][0 if age_days <= 2 else 1] += 1

    out = {}
    for t, by_author in contrib.items():
        raw = 0.0
        author_totals = {}
        for a, vals in by_author.items():
            # 同一アカウントの連投は逓減（最大寄与 + 残りの25%、ただし最大寄与の1.5倍まで）
            top = max(vals, key=abs)
            extra = 0.25 * (sum(vals) - top)
            total = top + math.copysign(min(abs(extra), 0.5 * abs(top)), extra)
            author_totals[a] = total
            raw += total
        wsum = sum(w for w, _ in sentiments[t])
        avg_sent = sum(w * s for w, s in sentiments[t]) / wsum if wsum else 0.0
        recent, old = recent_vs_old[t]
        top_authors = sorted(author_totals.items(), key=lambda kv: -kv[1])[:3]
        out[t] = {
            "raw": raw,
            "mentions": len(sentiments[t]),
            "unique_authors": len(by_author),
            "sentiment": avg_sent,
            "bullish_authors": sum(1 for v in author_totals.values() if v > 0),
            "bearish_authors": sum(1 for v in author_totals.values() if v < 0),
            "buzz_ratio": (recent + 1) / (old + 1),
            "top_authors": [names[a] for a, _ in top_authors],
        }
    # 投稿量は週や市場環境で大きく変わるため、その週の最大値を基準に相対評価（最大≒0.96）
    scale = max(cfg.social_scale_floor, max((abs(v["raw"]) for v in out.values()), default=0) / 2)
    for v in out.values():
        v["social"] = (math.tanh(v["raw"] / scale) + 1) / 2
    return out


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def technical_score(df: pd.DataFrame) -> tuple[float, dict]:
    """エントリー前日までの日足からトレンド・モメンタム・過熱感を評価（0〜1）。"""
    if len(df) < 30:
        return 0.5, {"note": "insufficient_data"}
    close = df["Close"]
    c = close.iloc[-1]
    sma5, sma25 = ind.sma(close, 5).iloc[-1], ind.sma(close, 25).iloc[-1]
    rsi = ind.rsi(close).iloc[-1]
    ret5 = c / close.iloc[-6] - 1
    vol_ratio = df["Volume"].iloc[-5:].mean() / max(df["Volume"].iloc[-25:].mean(), 1)
    hist = ind.macd_hist(close)
    parts = {
        "trend": (0.5 * (c > sma25) + 0.5 * (sma5 > sma25)),
        # 5日リターン: +0〜8% を好感、急騰しすぎ（>15%）は反落リスクとして減点
        "momentum": _clip01(0.5 + ret5 * 6) if ret5 < 0.08 else _clip01(1 - (ret5 - 0.08) * 6),
        # RSI: 45〜65 が最良、75超は過熱
        "rsi": _clip01(1 - abs(rsi - 55) / 25) if not math.isnan(rsi) else 0.5,
        "volume": _clip01((vol_ratio - 0.8) / 0.8),
        "macd": 1.0 if hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2] else (0.6 if hist.iloc[-1] > 0 else 0.2),
    }
    weights = {"trend": 0.3, "momentum": 0.2, "rsi": 0.2, "volume": 0.15, "macd": 0.15}
    score = sum(parts[k] * weights[k] for k in weights)
    detail = {k: round(float(v), 3) for k, v in parts.items()}
    detail.update(rsi_value=round(float(rsi), 1), ret5=round(float(ret5) * 100, 2), vol_ratio=round(float(vol_ratio), 2))
    return float(score), detail


def fundamental_score(f: dict, week_start: date) -> tuple[float, dict]:
    """割安性・収益性・成長性（0〜1）。データがなければ中立 0.5。"""
    parts = {}
    per = f.get("per")
    if per is not None:
        parts["per"] = 0.1 if per <= 0 else _clip01(1 - abs(per - 15) / 30)
    pbr = f.get("pbr")
    if pbr is not None:
        parts["pbr"] = _clip01(1.2 - pbr / 4)
    roe = f.get("roe")
    if roe is not None:
        parts["roe"] = _clip01(roe / 0.15)
    g = f.get("revenue_growth")
    if g is not None:
        parts["growth"] = _clip01(0.5 + g * 2.5)
    score = sum(parts.values()) / len(parts) if parts else 0.5
    detail = {k: round(v, 3) for k, v in parts.items()}
    ne = f.get("next_earnings")
    if ne and week_start <= ne <= week_start + timedelta(days=4):
        detail["earnings_this_week"] = ne.isoformat()  # 決算跨ぎはギャンブル性が高い
    return float(score), detail


def score_week(posts: list[Post], week_start: date, as_of: datetime, provider: MarketDataProvider,
               extractor: TickerExtractor, cfg, credibility: dict[str, float] | None = None) -> list[TickerScore]:
    sc = cfg.scoring
    signals = social_signals(posts, as_of, extractor, sc, cfg.x.min_followers, credibility)
    results = []
    for ticker, s in signals.items():
        if s["unique_authors"] < sc.min_unique_authors:
            continue
        hist = provider.daily(ticker, week_start - timedelta(days=90), week_start - timedelta(days=1))
        if hist.empty:
            continue  # 上場廃止・誤抽出など
        tech, tdet = technical_score(hist)
        try:
            fund, fdet = fundamental_score(provider.fundamentals(ticker), week_start)
        except Exception:
            fund, fdet = 0.5, {}
        wsum = sc.weight_social + sc.weight_technical + sc.weight_fundamental
        total = 100 * (sc.weight_social * s["social"] + sc.weight_technical * tech
                       + sc.weight_fundamental * fund) / wsum
        if "earnings_this_week" in fdet:
            total *= 0.9
        results.append(TickerScore(
            ticker=ticker, score=round(total, 2), social=round(s["social"], 4), technical=round(tech, 4),
            fundamental=round(fund, 4), mentions=s["mentions"], unique_authors=s["unique_authors"],
            sentiment=round(s["sentiment"], 3),
            detail={"social": {k: v for k, v in s.items() if k not in ("social",)}, "technical": tdet,
                    "fundamental": fdet, "last_close": float(hist["Close"].iloc[-1])},
        ))
    results.sort(key=lambda r: -r.score)
    for i, r in enumerate(results, 1):
        r.rank = i
    return results


def pick(scores: list[TickerScore], cfg) -> list[TickerScore]:
    sc = cfg.scoring
    return [s for s in scores if s.score >= sc.min_score and s.sentiment > 0][: sc.top_n]
