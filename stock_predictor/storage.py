"""SQLite 永続化（投稿・ランキング・仮想取引・アカウント別の的中実績）。"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import Author, Post, TickerScore, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY, author_id TEXT, username TEXT, followers INTEGER, verified INTEGER,
  text TEXT, created_at TEXT, likes INTEGER, retweets INTEGER, replies INTEGER, quotes INTEGER, lang TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at);
CREATE TABLE IF NOT EXISTS rankings (
  week TEXT, ticker TEXT, rank INTEGER, score REAL, social REAL, technical REAL, fundamental REAL,
  mentions INTEGER, unique_authors INTEGER, sentiment REAL, detail TEXT, PRIMARY KEY (week, ticker)
);
CREATE TABLE IF NOT EXISTS trades (
  week TEXT, ticker TEXT, score REAL, entry_date TEXT, entry_price REAL, shares INTEGER,
  exit_date TEXT, exit_price REAL, exit_reason TEXT, status TEXT, hold_return_pct REAL, fees REAL,
  PRIMARY KEY (week, ticker)
);
CREATE TABLE IF NOT EXISTS author_calls (
  week TEXT, author_id TEXT, username TEXT, ticker TEXT, sentiment REAL, realized_return REAL,
  PRIMARY KEY (week, author_id, ticker)
);
CREATE TABLE IF NOT EXISTS benchmark (week TEXT PRIMARY KEY, ticker TEXT, return_pct REAL);
"""


def _d(s):
    return date.fromisoformat(s) if s else None


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    # --- posts
    def save_posts(self, posts: list[Post]) -> int:
        cur = self.db.executemany(
            "INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(p.id, p.author.id, p.author.username, p.author.followers, int(p.author.verified), p.text,
              p.created_at.isoformat(), p.likes, p.retweets, p.replies, p.quotes, p.lang) for p in posts])
        self.db.commit()
        return cur.rowcount

    def load_posts(self, start: datetime, end: datetime, min_followers: int = 0) -> list[Post]:
        rows = self.db.execute("SELECT * FROM posts WHERE followers >= ?", (min_followers,)).fetchall()
        out = []
        for r in rows:
            created = datetime.fromisoformat(r[6])
            if start <= created < end:
                out.append(Post(r[0], Author(r[1], r[2], r[3], bool(r[4])), r[5], created,
                                r[7], r[8], r[9], r[10], r[11]))
        return out

    # --- rankings
    def save_ranking(self, week: str, scores: list[TickerScore]):
        self.db.execute("DELETE FROM rankings WHERE week=?", (week,))
        self.db.executemany(
            "INSERT INTO rankings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(week, s.ticker, s.rank, s.score, s.social, s.technical, s.fundamental, s.mentions,
              s.unique_authors, s.sentiment, json.dumps(s.detail, ensure_ascii=False, default=str)) for s in scores])
        self.db.commit()

    def load_ranking(self, week: str) -> list[TickerScore]:
        rows = self.db.execute("SELECT * FROM rankings WHERE week=? ORDER BY rank", (week,)).fetchall()
        return [TickerScore(r[1], r[3], r[4], r[5], r[6], r[7], r[8], r[9], json.loads(r[10]), r[2]) for r in rows]

    # --- trades
    def save_trade(self, t: Trade):
        self.db.execute(
            "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.week, t.ticker, t.score, t.entry_date.isoformat(), t.entry_price, t.shares,
             t.exit_date.isoformat() if t.exit_date else None, t.exit_price, t.exit_reason, t.status,
             t.hold_return_pct, t.fees))
        self.db.commit()

    def load_trades(self, week: str | None = None) -> list[Trade]:
        q, args = "SELECT * FROM trades", ()
        if week:
            q, args = q + " WHERE week=?", (week,)
        rows = self.db.execute(q + " ORDER BY week, score DESC", args).fetchall()
        return [Trade(r[0], r[1], r[2], _d(r[3]), r[4], r[5], _d(r[6]), r[7], r[8], r[9], r[10], r[11] or 0.0)
                for r in rows]

    # --- benchmark
    def save_benchmark(self, week: str, ticker: str, ret: float | None):
        self.db.execute("INSERT OR REPLACE INTO benchmark VALUES (?,?,?)", (week, ticker, ret))
        self.db.commit()

    def load_benchmarks(self) -> dict[str, float]:
        return {w: r for w, r in self.db.execute("SELECT week, return_pct FROM benchmark") if r is not None}

    # --- author credibility
    def save_author_calls(self, week: str, calls: list[tuple]):
        """calls: (author_id, username, ticker, sentiment, realized_return)"""
        self.db.executemany("INSERT OR REPLACE INTO author_calls VALUES (?,?,?,?,?,?)",
                            [(week, *c) for c in calls])
        self.db.commit()

    def author_credibility(self, before_week: str, prior: float = 2.0) -> dict[str, float]:
        """過去コールの的中率（ベイズ平滑化）→ 重み。的中率50%で1.0、70%で約2.0、30%で約0.36。"""
        rows = self.db.execute(
            "SELECT author_id, SUM(CASE WHEN sentiment * realized_return > 0 THEN 1 ELSE 0 END), COUNT(*) "
            "FROM author_calls WHERE week < ? AND sentiment != 0 AND realized_return IS NOT NULL "
            "GROUP BY author_id", (before_week,)).fetchall()
        return {a: min(2.5, max(0.25, ((hits + prior) / (n + 2 * prior) / 0.5) ** 2)) for a, hits, n in rows}

    def author_stats(self) -> list[tuple]:
        return self.db.execute(
            "SELECT username, COUNT(*), SUM(CASE WHEN sentiment * realized_return > 0 THEN 1 ELSE 0 END), "
            "AVG(CASE WHEN sentiment > 0 THEN realized_return END) FROM author_calls "
            "WHERE sentiment != 0 AND realized_return IS NOT NULL GROUP BY author_id ORDER BY COUNT(*) DESC"
        ).fetchall()
