"""X API v2 クライアント。

- 検索モード: GET /2/tweets/search/recent（直近7日。Basic プラン以上が必要）
- アカウント指定モード: GET /2/users/by → GET /2/users/:id/tweets
いずれも user.fields=public_metrics でフォロワー数を取得し、min_followers 未満を除外する。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

from ..models import Author, Post

API = "https://api.x.com/2"
TWEET_FIELDS = "created_at,public_metrics,lang,author_id"
USER_FIELDS = "public_metrics,verified,username"


class XClient:
    def __init__(self, bearer_token: str, session: requests.Session | None = None):
        if not bearer_token:
            raise ValueError("X API の Bearer Token が未設定です（X_BEARER_TOKEN）")
        self.s = session or requests.Session()
        self.s.headers["Authorization"] = f"Bearer {bearer_token}"

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(5):
            r = self.s.get(f"{API}{path}", params=params, timeout=30)
            if r.status_code == 429:  # レート制限: リセット時刻まで待機
                reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
                time.sleep(max(1, reset - time.time()) + 1)
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    @staticmethod
    def _parse(payload: dict, users: dict[str, Author], min_followers: int) -> list[Post]:
        for u in payload.get("includes", {}).get("users", []):
            users[u["id"]] = Author(u["id"], u["username"], u["public_metrics"]["followers_count"],
                                    bool(u.get("verified")))
        posts = []
        for t in payload.get("data", []):
            a = users.get(t["author_id"])
            if a is None or a.followers < min_followers:
                continue
            m = t.get("public_metrics", {})
            posts.append(Post(
                id=t["id"], author=a, text=t["text"],
                created_at=datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
                likes=m.get("like_count", 0), retweets=m.get("retweet_count", 0),
                replies=m.get("reply_count", 0), quotes=m.get("quote_count", 0), lang=t.get("lang"),
            ))
        return posts

    def search_recent(self, query: str, start: datetime, end: datetime, min_followers: int,
                      lang: str | None = None, max_pages: int = 10) -> list[Post]:
        q = f"{query} lang:{lang}" if lang else query
        params = {
            "query": q, "max_results": 100, "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id", "user.fields": USER_FIELDS,
            "start_time": _iso(start), "end_time": _iso(min(end, datetime.now(timezone.utc) - timedelta(seconds=30))),
        }
        users: dict[str, Author] = {}
        posts: list[Post] = []
        for _ in range(max_pages):
            payload = self._get("/tweets/search/recent", params)
            posts += self._parse(payload, users, min_followers)
            token = payload.get("meta", {}).get("next_token")
            if not token:
                break
            params["next_token"] = token
        return posts

    def user_timelines(self, usernames: list[str], start: datetime, end: datetime,
                       min_followers: int, max_pages: int = 3) -> list[Post]:
        posts: list[Post] = []
        for i in range(0, len(usernames), 100):
            data = self._get("/users/by", {"usernames": ",".join(usernames[i:i + 100]), "user.fields": USER_FIELDS})
            for u in data.get("data", []):
                author = Author(u["id"], u["username"], u["public_metrics"]["followers_count"], bool(u.get("verified")))
                if author.followers < min_followers:
                    continue
                params = {"max_results": 100, "tweet.fields": TWEET_FIELDS, "exclude": "retweets",
                          "start_time": _iso(start), "end_time": _iso(end)}
                for _ in range(max_pages):
                    payload = self._get(f"/users/{author.id}/tweets", params)
                    posts += self._parse(payload, {author.id: author}, min_followers)
                    token = payload.get("meta", {}).get("next_token")
                    if not token:
                        break
                    params["pagination_token"] = token
        return posts


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
