"""BカートAPI クライアント。

Bカートの「会員別価格」には2系統ある（機能ページより）:
  A) 価格グループ（ステージ）ごとの掛け率  … グループに会員を紐付けて一括適用
  B) 会員ID別・商品別の個別単価          … 1会員1商品ごとの単価

本 PoC は「会員別価格（掛け率）を外部から更新できるか」の検証なので、
A を主経路、B を代替経路として両方を試せるようにしてある。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from common.config import env, load_endpoints
from common.http import ApiClient, RateLimiter, Response
from common.timing import Recorder


class BcartClient:
    def __init__(
        self,
        recorder: Recorder,
        *,
        trace_path: Path | None = None,
        verbose: bool = False,
        base_url_override: str | None = None,
        token_url_override: str | None = None,
    ) -> None:
        self.cfg = load_endpoints()
        self.spec = self.cfg["bcart"]
        self.recorder = recorder
        self.client_id = env("BCART_CLIENT_ID", required=True)
        self.client_secret = env("BCART_CLIENT_SECRET", required=True)
        # 認可コードフローで払い出したトークンを直接使う運用も許可する。
        self.static_token = env("BCART_ACCESS_TOKEN", "")

        self.token_url = token_url_override or self.spec["auth"]["token_url"]
        base_url = base_url_override or self.spec["api_base"]["production"]

        rl = self.spec["rate_limit"]
        self.api = ApiClient(
            base_url,
            vendor="bcart",
            recorder=recorder,
            # 300req/300sec を超えると300秒ロック。既定は 1req/sec で安全側。
            rate_limiter=RateLimiter(float(rl.get("max_requests_per_sec", 1))),
            trace_path=trace_path,
            verbose=verbose,
        )

    def authenticate(self) -> str:
        if self.static_token:
            self.api.set_bearer(self.static_token)
            return self.static_token
        with self.recorder.measure("bcart:auth", self.token_url) as m:
            resp = requests.post(
                self.token_url,
                data={
                    "grant_type": self.spec["auth"]["grant_type"],
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=30,
            )
            m.status_code = resp.status_code
            m.ok = resp.ok
        if not resp.ok:
            raise SystemExit(
                f"Bカート認証に失敗しました ({resp.status_code}): {resp.text[:300]}\n"
                "→ 認可方式（認可コード/クライアントクレデンシャル）が"
                "トライアル環境の払い出しと一致しているか確認してください。\n"
                "→ 認可コード方式の場合は BCART_ACCESS_TOKEN に直接トークンを設定できます。"
            )
        token = resp.json()["access_token"]
        self.api.set_bearer(token)
        return token

    def _ep(self, name: str) -> tuple[str, str]:
        spec = self.spec["endpoints"][name]
        return spec["method"], spec["path"]

    def list_items(self, limit: int = 100) -> list[dict[str, Any]]:
        method, path = self._ep("list_items")
        resp = self.api.request(
            method, path, label="bcart:list_items", params={"limit": limit}
        )
        return _as_list(resp)

    def list_customers(self, limit: int = 100) -> list[dict[str, Any]]:
        method, path = self._ep("list_customers")
        resp = self.api.request(
            method, path, label="bcart:list_customers", params={"limit": limit}
        )
        return _as_list(resp)

    def list_stages(self) -> list[dict[str, Any]]:
        method, path = self._ep("list_stages")
        resp = self.api.request(method, path, label="bcart:list_stages")
        return _as_list(resp)

    # -- 経路A: 価格グループの掛け率を更新 -----------------------------------
    def update_stage_rate(self, stage_id: str, rate: float) -> Response:
        """価格グループ（ステージ）の掛け率を更新する。

        1リクエストでそのグループに属する全会員・全商品に効くため、
        「更新1件あたり」の定義が会員別個別単価とは大きく異なる点に注意。
        報告書ではこの2つを必ず分けて計測値を示すこと。
        """
        method, path = self._ep("update_stage")
        return self.api.request(
            method,
            path.replace("{stage_id}", str(stage_id)),
            label="bcart:update_stage_rate",
            target=f"stage={stage_id}",
            json_body={"rate": rate},
        )

    # -- 経路B: 会員ID別の個別単価を更新 -------------------------------------
    def update_item_price(
        self, item_id: str, customer_id: str, price: int
    ) -> Response:
        method, path = self._ep("update_item_price")
        return self.api.request(
            method,
            path.replace("{item_id}", str(item_id)),
            label="bcart:update_item_price",
            target=f"item={item_id},customer={customer_id}",
            json_body={"customer_id": customer_id, "price": price},
        )

    def assign_customer_stage(self, customer_id: str, stage_id: str) -> Response:
        method, path = self._ep("update_customer")
        return self.api.request(
            method,
            path.replace("{customer_id}", str(customer_id)),
            label="bcart:assign_stage",
            target=f"customer={customer_id}",
            json_body={"stage_id": stage_id},
        )


def _as_list(resp: Response) -> list[dict[str, Any]]:
    if not resp.ok:
        return []
    body = resp.body
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "items", "customers", "stages", "result"):
            if isinstance(body.get(key), list):
                return body[key]
    return []
