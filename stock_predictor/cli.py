from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from . import pipeline as pl
from .config import load_config
from .extractor import TickerExtractor
from .paper_trader import PaperTrader, week_id
from .report import author_table, format_ranking, format_summary, format_trades, summarize
from .scorer import pick
from .storage import Store

DISCLAIMER = "※ 本ツールは研究・検証用です。投資判断は自己責任で行ってください。"


def _week(arg: str | None, default: date) -> date:
    return pl.as_monday(date.fromisoformat(arg)) if arg else default


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stock_predictor", description="X投稿から来週上がる株をスコアリングし仮想売買で検証")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="X API（または JSONL ファイル）から投稿を収集")
    c.add_argument("--file", help="JSONL ファイルから読み込む")
    c.add_argument("--week", help="対象週の月曜（既定: 次の月曜）")
    for name, h in [("score", "来週の銘柄スコアを算出して表示"), ("buy", "月曜寄付きで仮想買い"),
                    ("update", "日足で売却判定（毎日引け後に実行）"), ("evaluate", "週末に結果を確定・アカウント信頼度を更新"),
                    ("run-week", "スコア→買い→売り→評価を1週分まとめて実行"), ("trades", "取引一覧")]:
        p = sub.add_parser(name, help=h)
        p.add_argument("--week", help="対象週の月曜 YYYY-MM-DD")
        if name == "update":
            p.add_argument("--through", help="この日までの日足で判定（既定: 今日）")
        if name == "score":
            p.add_argument("--limit", type=int, default=20)
    b = sub.add_parser("backtest", help="期間内の各週で run-week を実行（DB に投稿が必要）")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    sub.add_parser("report", help="検証レポート")
    sub.add_parser("authors", help="アカウント別の的中実績")
    d = sub.add_parser("demo", help="擬似データでオフラインデモ")
    d.add_argument("--weeks", type=int, default=12)
    d.add_argument("--db", default=":memory:")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.cmd == "demo":
        return _demo(cfg, args)

    store = Store(cfg.db_path)
    extractor = TickerExtractor(cfg.scoring.market)
    today = pl.today_local(cfg)
    upcoming = today if today.weekday() == 0 else pl.next_monday(today)

    if args.cmd == "collect":
        wk = _week(args.week, upcoming)
        start, end = pl.window(cfg, wk)
        if args.file:
            from .sources.file_source import load_jsonl
            posts = load_jsonl(args.file, cfg.x.min_followers)
            store.save_posts(posts)
        else:
            posts = pl.collect(cfg, store, start, end)
        print(f"{len(posts)} 件の投稿を保存しました（フォロワー {cfg.x.min_followers:,} 人以上）")
        return 0

    from .market_data import make_provider
    provider = make_provider(cfg)
    if args.cmd == "score":
        wk = _week(args.week, upcoming)
        ranking = pl.score(cfg, store, provider, wk, extractor)
        print(f"■ {wk} 週の予想ランキング")
        print(format_ranking(ranking, args.limit))
        print("\n買い候補:", ", ".join(f"{s.ticker}({s.score:.0f})" for s in pick(ranking, cfg)) or "なし")
        print(DISCLAIMER)
    elif args.cmd == "buy":
        wk = _week(args.week, pl.as_monday(today))
        ranking = store.load_ranking(week_id(wk)) or pl.score(cfg, store, provider, wk, extractor)
        trades = PaperTrader(cfg, provider, store).open_week(wk, pick(ranking, cfg))
        print(format_trades(trades) if trades else "新規の買いはありません（寄付き前の場合は寄付き後に再実行）")
    elif args.cmd == "update":
        wk = _week(args.week, pl.as_monday(today))
        through = date.fromisoformat(args.through) if args.through else today
        print(format_trades(PaperTrader(cfg, provider, store).update(wk, through)))
    elif args.cmd == "evaluate":
        wk = _week(args.week, pl.as_monday(today))
        calls = pl.evaluate_week(cfg, store, provider, wk, extractor)
        print(f"{len(calls)} 件のアカウント別コールを記録しました")
    elif args.cmd == "run-week":
        wk = _week(args.week, pl.as_monday(today))
        ranking, picks, trades = pl.run_week(cfg, store, provider, wk, extractor, min(today, wk + timedelta(days=4)))
        print(format_ranking(ranking, 10), "\n")
        print(format_trades(trades))
    elif args.cmd == "backtest":
        wk = pl.as_monday(date.fromisoformat(args.start))
        end = date.fromisoformat(args.end)
        while wk <= end:
            pl.run_week(cfg, store, provider, wk, extractor)
            wk += timedelta(weeks=1)
        print(format_summary(summarize(store.load_trades(), store.load_benchmarks())))
    elif args.cmd == "trades":
        print(format_trades(store.load_trades(week_id(_week(args.week, pl.as_monday(today))) if args.week else None)))
    elif args.cmd == "report":
        print(format_summary(summarize(store.load_trades(), store.load_benchmarks())))
    elif args.cmd == "authors":
        print(author_table(store.author_stats()))
    return 0


def _demo(cfg, args):
    from .demo import build
    cfg.market_data.benchmark = "1306.T"
    posts, provider, mondays = build(args.weeks)
    store = Store(args.db)
    store.save_posts([p for p in posts if p.author.followers >= cfg.x.min_followers])
    print(f"擬似投稿 {len(posts)} 件（フォロワー1万人以上: {len(store.load_posts(*pl.window(cfg, mondays[-1])))} 件/直近週）")
    extractor = TickerExtractor("jp")
    for wk in mondays:
        ranking, picks, trades = pl.run_week(cfg, store, provider, wk, extractor)
        rets = [f"{t.ticker}:{t.return_pct:+.1f}%({t.exit_reason})" for t in trades if t.return_pct is not None]
        print(f"{wk}  買い {len(trades)} 銘柄  " + " ".join(rets))
    print("\n■ 最終週ランキング")
    print(format_ranking(store.load_ranking(week_id(mondays[-1])), 10))
    print()
    print(format_summary(summarize(store.load_trades(), store.load_benchmarks())))
    print("\n■ アカウント別実績（上位）")
    print(author_table(store.author_stats()[:10]))
    print("\n" + DISCLAIMER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
