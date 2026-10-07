from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from stock_predictor import pipeline as pl
from stock_predictor.config import Config, TradingConfig
from stock_predictor.extractor import TickerExtractor
from stock_predictor.market_data import MarketDataProvider
from stock_predictor.models import Author, Post, TickerScore
from stock_predictor.paper_trader import PaperTrader
from stock_predictor.report import summarize
from stock_predictor.scorer import author_weight, social_signals
from stock_predictor.sentiment import analyze
from stock_predictor.sources.x_api import XClient
from stock_predictor.storage import Store
from stock_predictor.strategy import simulate_exit


# ---------- extractor
@pytest.fixture
def ex():
    return TickerExtractor("both", jp_names={"トヨタ": "7203", "ソニー": "6758"}, jp_universe={"7203", "6758"})


def test_extracts_codes_names_and_cashtags(ex):
    assert ex.extract("【7203】トヨタ 好決算") == ["7203.T"]
    assert ex.extract("ソニーと $NVDA を買い") == ["NVDA", "6758.T"]
    assert ex.extract("(130A)が強い") == ["130A.T"]
    assert ex.extract("9999.T をチェック") == ["9999.T"]


def test_ignores_years_prices_and_quantities(ex):
    assert ex.extract("2026年は1500円で100株買った、+3000") == []
    assert ex.extract("$USD が強い") == []
    # 未知コードは文脈がなければ採用しない
    assert ex.extract("今日は 4321 回目の挑戦") == []


def test_fullwidth_normalized(ex):
    assert ex.extract("（７２０３）") == ["7203.T"]


# ---------- sentiment
def test_sentiment_polarity():
    assert analyze("上方修正で爆上げ、買い増し") > 0.5
    assert analyze("下方修正で暴落、損切り") < -0.5
    assert analyze("決算日はいつ") == 0
    assert analyze("全然上がらない") < 0
    assert analyze("売られすぎで下げ止まり") > 0


# ---------- scorer
def _post(pid, author, text, hours_ago=10, likes=0, now=datetime(2026, 10, 12, tzinfo=timezone.utc)):
    return Post(str(pid), author, text, now - timedelta(hours=hours_ago), likes=likes)


def test_author_weight_log_scale():
    assert author_weight(10_000, 10_000) == pytest.approx(1.0)
    assert author_weight(100_000, 10_000) == pytest.approx(2.0)


def test_social_signals_spam_and_breadth(ex):
    cfg = Config().scoring
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    a, b = Author("a", "a", 20_000), Author("b", "b", 20_000)
    spam = [_post(i, a, "【7203】買い") for i in range(10)]
    broad = [_post(100, a, "【6758】買い"), _post(101, b, "【6758】買い")]
    s = social_signals(spam + broad, now, ex, cfg, 10_000)
    assert s["6758.T"]["raw"] > s["7203.T"]["raw"]  # 1人の連投 < 2人の言及
    assert s["6758.T"]["unique_authors"] == 2


def test_credibility_reweights(ex):
    cfg = Config().scoring
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    a = Author("a", "a", 20_000)
    p = [_post(1, a, "【7203】買い")]
    base = social_signals(p, now, ex, cfg, 10_000)["7203.T"]["raw"]
    low = social_signals(p, now, ex, cfg, 10_000, {"a": 0.5})["7203.T"]["raw"]
    assert low == pytest.approx(base * 0.5)


# ---------- strategy
def _bars(rows, start=date(2026, 10, 12)):
    idx = [start + timedelta(days=i) for i in range(len(rows))]
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def _history(n=60, price=1000.0, rng=0.01):
    start = date(2026, 10, 12) - timedelta(days=n)
    rows = [(price, price * (1 + rng), price * (1 - rng), price, 1000) for _ in range(n)]
    return _bars(rows, start)


P = TradingConfig(momentum_exit=False, rsi_exit=101, signal_execution="close")


def test_stop_loss_hit():
    week = _bars([(1000, 1005, 990, 1000, 1000), (1000, 1001, 900, 950, 1000)])
    r = simulate_exit(week.index[0], 1000, _history(), week, P, week_complete=False)
    assert r.reason == "stop_loss" and r.price == pytest.approx(970)  # min_stop 3%


def test_take_profit_hit():
    week = _bars([(1000, 1100, 995, 1050, 1000)])
    r = simulate_exit(week.index[0], 1000, _history(), week, P, week_complete=False)
    # ATR≒20（2%）× 3 = 6% が min_take_profit 5% を上回る
    assert r.reason == "take_profit" and r.price == pytest.approx(1060)


def test_gap_down_fills_at_open():
    week = _bars([(1000, 1010, 995, 1000, 1000), (900, 910, 890, 905, 1000)])
    r = simulate_exit(week.index[0], 1000, _history(), week, P, week_complete=False)
    assert r.reason == "stop_loss_gap" and r.price == 900


def test_forced_exit_at_week_end_and_open_midweek():
    rows = [(1000, 1010, 995, 1005, 1000)] * 5
    week = _bars(rows)
    assert simulate_exit(week.index[0], 1000, _history(), week.iloc[:3], P, week_complete=False) is None
    r = simulate_exit(week.index[0], 1000, _history(), week, P, week_complete=True)
    assert r.reason == "week_end_close" and r.date == week.index[-1]


def test_trailing_stop():
    week = _bars([(1000, 1045, 999, 1040, 1000), (1040, 1042, 1000, 1005, 1000)])
    r = simulate_exit(week.index[0], 1000, _history(), week, P, week_complete=False)
    assert r.reason == "trailing_stop" and r.price == pytest.approx(1045 * 0.97)


def test_earnings_avoid():
    week = _bars([(1000, 1010, 995, 1005, 1000)] * 3)
    r = simulate_exit(week.index[0], 1000, _history(), week, P, False, next_earnings=week.index[2])
    assert r.reason == "earnings_avoid" and r.date == week.index[1]


def test_signal_next_open_execution():
    p = TradingConfig(momentum_exit=False, rsi_exit=101, signal_execution="next_open")
    week = _bars([(1000, 1010, 995, 1005, 1000), (1003, 1010, 995, 1008, 1000), (1001, 1010, 995, 1005, 1000)])
    r = simulate_exit(week.index[0], 1000, _history(), week, p, False, next_earnings=week.index[2])
    assert r.reason == "earnings_avoid" and r.date == week.index[2] and r.price == 1001


# ---------- paper trader / pipeline
class FixedProvider(MarketDataProvider):
    def __init__(self, frames):
        self.frames = frames

    def daily(self, ticker, start, end):
        df = self.frames.get(ticker)
        if df is None:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        return df[(df.index >= start) & (df.index <= end)]


def test_paper_trader_buys_monday_open_in_lots():
    monday = date(2026, 10, 12)
    week = _bars([(1234, 1240, 1230, c, 1000) for c in (1235, 1233, 1236, 1232, 1234)], monday)
    df = pd.concat([_history(price=1234), week])
    cfg = Config()
    cfg.trading.slippage_bps = 0
    cfg.trading.rsi_exit = 101  # 横ばいの合成データでは RSI が極端になるため無効化
    cfg.trading.momentum_exit = False
    store = Store(":memory:")
    t = PaperTrader(cfg, FixedProvider({"7203.T": df}), store)
    trades = t.open_week(monday, [TickerScore("7203.T", 80, 1, 1, 1, 3, 2, 0.5)])
    assert trades[0].entry_price == 1234 and trades[0].shares % 100 == 0
    assert trades[0].shares == 400  # 600,000 / (1234*100) → 4単元
    closed = t.update(monday, monday + timedelta(days=4))
    assert closed[0].status == "closed" and closed[0].exit_reason == "week_end_close"
    assert summarize(closed, {})["trades"] == 1


def test_window_and_week_helpers():
    cfg = Config()
    start, end = pl.window(cfg, date(2026, 10, 12))
    assert end.isoformat().startswith("2026-10-12T00:00:00+09:00")
    assert (end - start).days == 7
    assert pl.next_monday(date(2026, 10, 7)) == date(2026, 10, 12)
    assert pl.next_monday(date(2026, 10, 12)) == date(2026, 10, 19)
    assert pl.as_monday(date(2026, 10, 9)) == date(2026, 10, 5)


# ---------- X API parsing
def test_x_parse_filters_followers():
    payload = {
        "data": [{"id": "1", "author_id": "u1", "text": "【7203】買い", "created_at": "2026-10-10T00:00:00.000Z",
                  "public_metrics": {"like_count": 5, "retweet_count": 1}},
                 {"id": "2", "author_id": "u2", "text": "x", "created_at": "2026-10-10T00:00:00.000Z"}],
        "includes": {"users": [{"id": "u1", "username": "big", "public_metrics": {"followers_count": 12000}},
                               {"id": "u2", "username": "small", "public_metrics": {"followers_count": 50}}]},
    }
    posts = XClient._parse(payload, {}, 10_000)
    assert [p.author.username for p in posts] == ["big"] and posts[0].likes == 5


def test_demo_runs():
    from stock_predictor.cli import main
    assert main(["demo", "--weeks", "4"]) == 0
