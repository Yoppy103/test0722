"""オフラインデモ: 擬似投稿 + 擬似株価で、スコアリング→仮想売買→検証まで一通り動かす。

擬似データでは「的中率の高いアカウント」が強気に言及した銘柄に翌週わずかな上昇バイアスを、
「煽り系アカウント」の推奨銘柄には下落バイアスを与えている（ツールが信号を拾えるかの確認用）。
実際の相場でこうした関係が成り立つ保証はない。
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .extractor import load_jp_names
from .market_data import SyntheticProvider
from .models import Author, Post

BULL = ["{n}({c})は来週も上昇期待。買い増しした", "【{c}】{n} 好決算で上方修正、本命", "{c} {n} 底打ち反発、ブレイク狙いで仕込み🚀",
        "{n}が高値更新、まだ強い。注目しておきたい"]
BEAR = ["{n}({c})は天井っぽい、利確して撤退", "【{c}】{n} 下方修正で暴落、損切り", "{n}は割高、空売り検討"]
NEUTRAL = ["{n}({c})の決算はいつだっけ", "今日は{n}の出来高が多い"]


def build(weeks: int = 12, end_monday: date = date(2026, 10, 5), seed: int = 7, tz: str = "Asia/Tokyo"):
    rng = random.Random(seed)
    names = load_jp_names()
    universe = sorted(set(names.values()))
    first_name = {}
    for n, c in names.items():
        first_name.setdefault(c, n)
    authors = (
        [("good", Author(f"g{i}", f"good_trader{i}", rng.randint(15_000, 300_000))) for i in range(6)]
        + [("pump", Author(f"p{i}", f"pump_king{i}", rng.randint(20_000, 800_000))) for i in range(4)]
        + [("noise", Author(f"n{i}", f"random_investor{i}", rng.randint(10_000, 80_000))) for i in range(10)]
        + [("small", Author(f"s{i}", f"small_acc{i}", rng.randint(500, 9_000))) for i in range(10)]  # 1万人未満→除外対象
    )
    drift = {}
    posts = []
    pid = 0
    zone = ZoneInfo(tz)
    mondays = [end_monday - timedelta(weeks=k) for k in range(weeks)][::-1]
    for monday in mondays:
        good_picks = rng.sample(universe, 3)
        pump_picks = rng.sample([c for c in universe if c not in good_picks], 2)
        for c in good_picks:
            drift[(f"{c}.T", monday)] = 0.006
        for c in pump_picks:
            drift[(f"{c}.T", monday)] = -0.004
        for kind, a in authors:
            for _ in range(rng.randint(2, 5)):
                if kind == "good":
                    c, tpl = rng.choice(good_picks), rng.choice(BULL)
                elif kind == "pump":
                    c, tpl = rng.choice(pump_picks), rng.choice(BULL)
                else:
                    c = rng.choice(universe)
                    tpl = rng.choice(BULL + BEAR + NEUTRAL)
                ts = datetime.combine(monday - timedelta(days=rng.randint(1, 6)), time(rng.randint(7, 23)), zone)
                pid += 1
                posts.append(Post(str(pid), a, tpl.format(n=first_name[c], c=c), ts,
                                  likes=rng.randint(0, 500), retweets=rng.randint(0, 80)))
    provider = SyntheticProvider(drift_by_week=drift, seed=seed)
    return posts, provider, mondays
