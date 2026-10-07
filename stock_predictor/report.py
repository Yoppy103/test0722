"""検証レポート: 勝率・平均リターン・ベンチマーク比較・スコアとリターンの相関・売却戦略の効果。"""
from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from .models import Trade


def summarize(trades: list[Trade], benchmarks: dict[str, float]) -> dict:
    closed = [t for t in trades if t.status == "closed" and t.return_pct is not None]
    if not closed:
        return {"trades": 0}
    df = pd.DataFrame([{
        "week": t.week, "ticker": t.ticker, "score": t.score, "ret": t.return_pct,
        "hold": t.hold_return_pct, "reason": t.exit_reason, "pnl": t.pnl,
    } for t in closed])
    weekly = df.groupby("week")["ret"].mean()
    bench = pd.Series({w: benchmarks.get(w) for w in weekly.index}, dtype=float)
    equity = (1 + weekly / 100).cumprod()
    dd = (equity / equity.cummax() - 1).min() * 100
    out = {
        "trades": len(df),
        "weeks": len(weekly),
        "win_rate": float((df["ret"] > 0).mean() * 100),
        "avg_return": float(df["ret"].mean()),
        "median_return": float(df["ret"].median()),
        "avg_win": float(df.loc[df["ret"] > 0, "ret"].mean()) if (df["ret"] > 0).any() else 0.0,
        "avg_loss": float(df.loc[df["ret"] <= 0, "ret"].mean()) if (df["ret"] <= 0).any() else 0.0,
        "total_pnl": float(df["pnl"].sum()),
        "cumulative_return": float((equity.iloc[-1] - 1) * 100),
        "max_drawdown": float(dd),
        "weekly_win_rate": float((weekly > 0).mean() * 100),
        "exit_reasons": dict(Counter(df["reason"])),
    }
    if bench.notna().any():
        excess = (weekly - bench).dropna()
        out["benchmark_avg_weekly"] = float(bench.mean())
        out["avg_excess_weekly"] = float(excess.mean())
        out["beat_benchmark_rate"] = float((excess > 0).mean() * 100)
    if df["hold"].notna().any():
        out["hold_to_friday_avg"] = float(df["hold"].mean())
        out["exit_strategy_edge"] = float(df["ret"].mean() - df["hold"].mean())
    if len(df) >= 5 and df["score"].nunique() > 1:
        out["score_return_corr"] = float(df["score"].rank().corr(df["ret"].rank()))
    return out


def format_summary(s: dict) -> str:
    if not s.get("trades"):
        return "決済済みの取引がまだありません。"
    lines = [
        "===== 仮想取引 検証レポート =====",
        f"取引数: {s['trades']}（{s['weeks']}週）",
        f"勝率: {s['win_rate']:.1f}%   週単位勝率: {s['weekly_win_rate']:.1f}%",
        f"平均リターン/取引: {s['avg_return']:+.2f}%（中央値 {s['median_return']:+.2f}%）",
        f"平均利益: {s['avg_win']:+.2f}%   平均損失: {s['avg_loss']:+.2f}%",
        f"累積リターン（週次等金額複利）: {s['cumulative_return']:+.2f}%   最大DD: {s['max_drawdown']:.2f}%",
        f"損益合計: {s['total_pnl']:+,.0f}",
    ]
    if "benchmark_avg_weekly" in s:
        lines.append(f"ベンチマーク平均週次: {s['benchmark_avg_weekly']:+.2f}%   超過リターン平均: "
                     f"{s['avg_excess_weekly']:+.2f}%   ベンチマーク勝ち週: {s['beat_benchmark_rate']:.1f}%")
    if "hold_to_friday_avg" in s:
        lines.append(f"金曜まで単純保有した場合: {s['hold_to_friday_avg']:+.2f}% → 売却戦略の効果: "
                     f"{s['exit_strategy_edge']:+.2f}pt")
    if "score_return_corr" in s:
        lines.append(f"スコアとリターンの順位相関: {s['score_return_corr']:+.3f}（正なら高スコアほど上がる傾向）")
    lines.append("売却理由: " + ", ".join(f"{k}={v}" for k, v in sorted(s["exit_reasons"].items(), key=lambda kv: -kv[1])))
    return "\n".join(lines)


def format_ranking(ranking, limit: int = 20) -> str:
    lines = [f"{'順位':>4} {'銘柄':<10} {'スコア':>6} {'SNS':>5} {'テク':>5} {'ファンダ':>6} {'言及':>4} {'人数':>4} {'感情':>6}  主な発信者"]
    for r in ranking[:limit]:
        top = ",".join(r.detail.get("social", {}).get("top_authors", []))
        flag = " ⚠決算" if "earnings_this_week" in r.detail.get("fundamental", {}) else ""
        lines.append(f"{r.rank:>4} {r.ticker:<10} {r.score:>6.1f} {r.social:>5.2f} {r.technical:>5.2f} "
                     f"{r.fundamental:>6.2f} {r.mentions:>4} {r.unique_authors:>4} {r.sentiment:>+6.2f}  {top}{flag}")
    return "\n".join(lines)


def format_trades(trades: list[Trade]) -> str:
    lines = [f"{'週':<11} {'銘柄':<9} {'買付日':<11} {'買値':>9} {'株数':>6} {'売却日':<11} {'売値':>9} {'損益%':>7} 理由"]
    for t in trades:
        r = f"{t.return_pct:+7.2f}" if t.return_pct is not None else "    保有中"
        lines.append(f"{t.week:<11} {t.ticker:<9} {t.entry_date!s:<11} {t.entry_price:>9.1f} {t.shares:>6} "
                     f"{(t.exit_date or '-')!s:<11} {(t.exit_price or 0):>9.1f} {r} {t.exit_reason or ''}")
    return "\n".join(lines)


def author_table(rows) -> str:
    lines = [f"{'アカウント':<20} {'コール数':>6} {'的中':>5} {'的中率':>7} {'強気時平均週次':>12}"]
    for u, n, hits, avg in rows:
        lines.append(f"@{u:<19} {n:>6} {hits:>5} {hits / n * 100:>6.1f}% {((avg or 0) * 100):>+11.2f}%")
    return "\n".join(lines)
