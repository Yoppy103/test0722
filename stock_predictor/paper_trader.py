"""仮想取引（ペーパートレード）。"""
from __future__ import annotations

from datetime import date, timedelta

from .market_data import MarketDataProvider
from .models import TickerScore, Trade
from .storage import Store
from .strategy import simulate_exit


def week_id(week_start: date) -> str:
    return week_start.isoformat()


class PaperTrader:
    def __init__(self, cfg, provider: MarketDataProvider, store: Store):
        self.cfg, self.provider, self.store = cfg, provider, store
        self.t = cfg.trading
        self.slip = self.t.slippage_bps / 10_000

    def _week_bars(self, ticker: str, week_start: date, through: date):
        return self.provider.daily(ticker, week_start, min(through, week_start + timedelta(days=4)))

    def open_week(self, week_start: date, picks: list[TickerScore]) -> list[Trade]:
        """週明け最初の営業日の寄付きで成行買い（寄付き価格 + スリッページ）。"""
        wid = week_id(week_start)
        existing = {t.ticker for t in self.store.load_trades(wid)}
        alloc = self.t.initial_capital / max(self.cfg.scoring.top_n, 1)
        trades = []
        for s in picks:
            if s.ticker in existing:
                continue
            bars = self._week_bars(s.ticker, week_start, week_start + timedelta(days=4))
            if bars.empty:
                continue
            d0 = bars.index[0]
            price = float(bars["Open"].iloc[0]) * (1 + self.slip)
            lot = self.t.lot_size
            shares = int(alloc // (price * lot)) * lot
            if shares == 0:
                continue  # 1単元も買えない
            t = Trade(wid, s.ticker, s.score, d0, price, shares, fees=price * shares * self.t.commission_rate)
            self.store.save_trade(t)
            trades.append(t)
        return trades

    def update(self, week_start: date, through: date) -> list[Trade]:
        """through 日までの日足で売却判定を再生する。"""
        week_complete = through >= week_start + timedelta(days=4)
        out = []
        for t in self.store.load_trades(week_id(week_start)):
            if t.status == "closed":
                out.append(t)
                continue
            history = self.provider.daily(t.ticker, t.entry_date - timedelta(days=120), t.entry_date - timedelta(days=1))
            bars = self._week_bars(t.ticker, week_start, through)
            bars = bars[bars.index >= t.entry_date]
            if bars.empty:
                out.append(t)
                continue
            try:
                ne = self.provider.fundamentals(t.ticker).get("next_earnings")
            except Exception:
                ne = None
            res = simulate_exit(t.entry_date, t.entry_price, history, bars, self.t, week_complete, ne, self.slip)
            if res:
                t.exit_date, t.exit_price, t.exit_reason, t.status = res.date, float(res.price), res.reason, "closed"
                t.fees += t.exit_price * t.shares * self.t.commission_rate
            if week_complete:
                last_close = float(bars["Close"].iloc[-1]) * (1 - self.slip)
                t.hold_return_pct = (last_close - t.entry_price) / t.entry_price * 100
            self.store.save_trade(t)
            out.append(t)
        return out

    def benchmark_return(self, week_start: date) -> float | None:
        b = self.provider.daily(self.cfg.market_data.benchmark, week_start, week_start + timedelta(days=4))
        if b.empty:
            return None
        return (float(b["Close"].iloc[-1]) / float(b["Open"].iloc[0]) - 1) * 100
