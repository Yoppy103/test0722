"""売却戦略: 月曜寄付き成行買い → チャート/ファンダメンタルを見て金曜引けまでに売却。

日足ベースで1日ずつ再生（ステートレス）するため、日中の途中経過でも、週が終わってからでも同じ結果になる。
ザラ場中の高値・安値の前後関係は日足では分からないため、同日に損切りと利確の両方に届いた場合は
保守的に損切りを優先する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from . import indicators as ind


@dataclass
class ExitPlan:
    stop: float
    take_profit: float
    stop_pct: float
    tp_pct: float


@dataclass
class ExitResult:
    date: date
    price: float
    reason: str


def plan_exits(history: pd.DataFrame, entry_price: float, p) -> ExitPlan:
    """エントリー前日までの ATR（ボラティリティ）から損切り・利確幅を決める。"""
    a = ind.atr(history).iloc[-1] if len(history) >= 15 else float("nan")
    vol = a / entry_price if a == a else p.min_stop_pct / p.stop_atr_mult
    stop_pct = min(p.max_stop_pct, max(p.min_stop_pct, p.stop_atr_mult * vol))
    tp_pct = max(p.min_take_profit_pct, p.take_profit_atr_mult * vol)
    return ExitPlan(entry_price * (1 - stop_pct), entry_price * (1 + tp_pct), stop_pct, tp_pct)


def simulate_exit(entry_date: date, entry_price: float, history: pd.DataFrame, week_bars: pd.DataFrame,
                  p, week_complete: bool, next_earnings: Optional[date] = None,
                  slippage: float = 0.0) -> Optional[ExitResult]:
    """week_bars: エントリー日以降の今週の日足。売却済みなら ExitResult、保有継続なら None。"""
    plan = plan_exits(history, entry_price, p)
    stop = plan.stop
    max_high = entry_price
    full = pd.concat([history, week_bars])
    close_all = full["Close"]
    ema5 = ind.ema(close_all, 5)
    rsi = ind.rsi(close_all)
    vol20 = full["Volume"].rolling(20, min_periods=5).mean().shift()
    pending: Optional[str] = None
    last_day = week_bars.index[-1] if len(week_bars) else None

    for i, (d, bar) in enumerate(week_bars.iterrows()):
        o, h, l, c = bar["Open"], bar["High"], bar["Low"], bar["Close"]
        # 前日引け後に出たシグナルを翌日寄りで執行
        if pending:
            return ExitResult(d, o * (1 - slippage), pending)
        if i > 0:
            if o <= stop:
                return ExitResult(d, o * (1 - slippage), "stop_loss_gap")
            if o >= plan.take_profit:
                return ExitResult(d, o * (1 - slippage), "take_profit_gap")
        if l <= stop:
            reason = "trailing_stop" if stop > plan.stop else "stop_loss"
            return ExitResult(d, stop * (1 - slippage), reason)
        if h >= plan.take_profit:
            return ExitResult(d, plan.take_profit, "take_profit")  # 指値なので滑りなし

        is_last = week_complete and d == last_day
        if is_last:
            return ExitResult(d, c * (1 - slippage), "week_end_close")

        # --- 引け時点のシグナル判定
        signal = None
        if rsi.loc[d] >= p.rsi_exit:
            signal = "rsi_overbought"
        elif p.momentum_exit and i >= 1:
            prev = week_bars.index[i - 1]
            if c < ema5.loc[d] and week_bars.loc[prev, "Close"] >= ema5.loc[prev]:
                signal = "momentum_loss"  # 5日EMA割れ
        if signal is None and c > entry_price:
            body = abs(c - o)
            upper = h - max(o, c)
            v20 = vol20.loc[d]
            if v20 == v20 and bar["Volume"] > 2.5 * v20 and upper > 2 * max(body, 1e-9):
                signal = "blowoff_top"  # 大商い + 長い上ヒゲ
        if signal is None and p.avoid_earnings and next_earnings and d < next_earnings <= _next_weekday(d):
            signal = "earnings_avoid"  # 決算発表の前営業日に手仕舞い

        if signal:
            if p.signal_execution == "close":
                return ExitResult(d, c * (1 - slippage), signal)
            pending = signal

        # トレーリングストップ更新（当日の値動きは翌日以降に反映 → 先読みなし）
        max_high = max(max_high, h)
        if max_high >= entry_price * (1 + p.trail_activate_pct):
            stop = max(stop, max_high * (1 - p.trail_pct))
    return None


def _next_weekday(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n
