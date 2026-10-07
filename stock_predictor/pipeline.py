"""週次ワークフロー: 収集 → スコアリング → 月曜寄りで買い → 日次で売却判定 → 週末に検証。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .extractor import TickerExtractor
from .market_data import MarketDataProvider
from .models import Post
from .paper_trader import PaperTrader, week_id
from .scorer import pick, score_week
from .sentiment import analyze
from .storage import Store


def next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7 or 7)


def as_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def window(cfg, week_start: date) -> tuple[datetime, datetime]:
    """スコアリングに使う投稿期間: 月曜 0:00（市場TZ）の直前 lookback_days 日。"""
    end = datetime.combine(week_start, time(0), ZoneInfo(cfg.timezone))
    return end - timedelta(days=cfg.x.lookback_days), end


def collect(cfg, store: Store, start: datetime, end: datetime) -> list[Post]:
    from .sources.x_api import XClient
    client = XClient(cfg.x.bearer_token)
    if cfg.x.accounts:
        posts = client.user_timelines(cfg.x.accounts, start, end, cfg.x.min_followers, cfg.x.max_pages)
    else:
        posts = client.search_recent(cfg.x.query, start, end, cfg.x.min_followers, cfg.x.lang, cfg.x.max_pages)
    store.save_posts(posts)
    return posts


def score(cfg, store: Store, provider: MarketDataProvider, week_start: date, extractor: TickerExtractor):
    start, end = window(cfg, week_start)
    posts = store.load_posts(start, end, cfg.x.min_followers)
    cred = store.author_credibility(week_id(week_start))
    ranking = score_week(posts, week_start, end, provider, extractor, cfg, cred)
    store.save_ranking(week_id(week_start), ranking)
    return ranking


def evaluate_week(cfg, store: Store, provider: MarketDataProvider, week_start: date, extractor: TickerExtractor):
    """週の結果を記録: ベンチマーク、および各アカウントの強気/弱気コールの当否（次週以降の信頼度に反映）。"""
    wid = week_id(week_start)
    trader = PaperTrader(cfg, provider, store)
    store.save_benchmark(wid, cfg.market_data.benchmark, trader.benchmark_return(week_start))
    realized = {}
    for s in store.load_ranking(wid):
        bars = provider.daily(s.ticker, week_start, week_start + timedelta(days=4))
        if not bars.empty:
            realized[s.ticker] = float(bars["Close"].iloc[-1]) / float(bars["Open"].iloc[0]) - 1
    start, end = window(cfg, week_start)
    agg: dict[tuple, list] = defaultdict(list)
    names = {}
    for p in store.load_posts(start, end, cfg.x.min_followers):
        sent = analyze(p.text)
        if sent == 0:
            continue
        for t in extractor.extract(p.text):
            if t in realized:
                agg[(p.author.id, t)].append(sent)
                names[p.author.id] = p.author.username
    calls = [(a, names[a], t, sum(v) / len(v), realized[t]) for (a, t), v in agg.items()]
    store.save_author_calls(wid, calls)
    return calls


def run_week(cfg, store: Store, provider: MarketDataProvider, week_start: date, extractor: TickerExtractor,
             through: date | None = None):
    """1週間分を一気に実行（過去週のバックテスト、または週末のまとめ実行）。"""
    ranking = score(cfg, store, provider, week_start, extractor)
    picks = pick(ranking, cfg)
    trader = PaperTrader(cfg, provider, store)
    trader.open_week(week_start, picks)
    through = through or week_start + timedelta(days=4)
    trades = trader.update(week_start, through)
    if through >= week_start + timedelta(days=4):
        evaluate_week(cfg, store, provider, week_start, extractor)
    return ranking, picks, trades


def today_local(cfg) -> date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(cfg.timezone)).date()
