"""JSONL ファイルから投稿を読み込む（過去データでのバックテストや、手動収集データ用）。

1行1投稿:
{"id": "1", "text": "...", "created_at": "2026-10-03T12:00:00+09:00",
 "author": {"id": "u1", "username": "foo", "followers": 25000},
 "likes": 10, "retweets": 2}
"""
from __future__ import annotations

import json
from datetime import datetime

from ..models import Author, Post


def load_jsonl(path: str, min_followers: int = 0) -> list[Post]:
    posts = []
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            d = json.loads(line)
            a = d["author"]
            author = Author(str(a["id"]), a["username"], int(a["followers"]), bool(a.get("verified")))
            if author.followers < min_followers:
                continue
            posts.append(Post(
                id=str(d["id"]), author=author, text=d["text"],
                created_at=datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")),
                likes=d.get("likes", 0), retweets=d.get("retweets", 0),
                replies=d.get("replies", 0), quotes=d.get("quotes", 0), lang=d.get("lang"),
            ))
    return posts
