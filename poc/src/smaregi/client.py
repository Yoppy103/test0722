"""スマレジ・プラットフォームAPI クライアント。"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import requests

from common.config import env, load_endpoints, resolve
from common.http import ApiClient, RateLimiter, Response
from common.timing import Recorder


class SmaregiClient:
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
        self.spec = self.cfg["smaregi"]
        self.recorder = recorder
        self.contract_id = env("SMAREGI_CONTRACT_ID", required=True)
        self.client_id = env("SMAREGI_CLIENT_ID", required=True)
        self.client_secret = env("SMAREGI_CLIENT_SECRET", required=True)
        self.store_id = env("SMAREGI_STORE_ID", "1")
        envname = env("SMAREGI_ENV", "sandbox")

        self.token_url = token_url_override or resolve(
            self.spec["auth"]["token_url"][envname], contract_id=self.contract_id
        )
        base_url = base_url_override or resolve(
            self.spec["api_base"][envname], contract_id=self.contract_id
        )
        self.api = ApiClient(
            base_url,
            vendor="smaregi",
            recorder=recorder,
            rate_limiter=RateLimiter(
                float(self.spec["rate_limit"].get("max_requests_per_sec", 5))
            ),
            trace_path=trace_path,
            verbose=verbose,
        )

    # -- 認証 ---------------------------------------------------------------
    def authenticate(self) -> str:
        """client_credentials でアクセストークンを取得する。

        トークン取得は「1件あたりの所要時間」には含めない（起動時1回のため）が、
        別ラベルで計測しておくと初回実行のオーバーヘッドを説明できる。
        """
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        with self.recorder.measure("smaregi:auth", self.token_url) as m:
            resp = requests.post(
                self.token_url,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": self.spec["auth"]["grant_type"],
                    "scope": " ".join(self.spec["auth"]["scopes"]),
                },
                timeout=30,
            )
            m.status_code = resp.status_code
            m.ok = resp.ok
        if not resp.ok:
            raise SystemExit(
                f"スマレジ認証に失敗しました ({resp.status_code}): {resp.text[:300]}\n"
                "→ contract_id / client_id / client_secret / スコープ設定を確認してください。"
            )
        token = resp.json()["access_token"]
        self.api.set_bearer(token)
        return token

    # -- 参照系 -------------------------------------------------------------
    def _ep(self, name: str) -> tuple[str, str]:
        spec = self.spec["endpoints"][name]
        return spec["method"], spec["path"]

    def list_products(self, limit: int = 100) -> list[dict[str, Any]]:
        method, path = self._ep("list_products")
        resp = self.api.request(
            method, path, label="smaregi:list_products", params={"limit": limit}
        )
        return _as_list(resp)

    def list_customers(self, limit: int = 100) -> list[dict[str, Any]]:
        method, path = self._ep("list_customers")
        resp = self.api.request(
            method, path, label="smaregi:list_customers", params={"limit": limit}
        )
        return _as_list(resp)

    def list_customer_groups(self) -> Response:
        method, path = self._ep("list_customer_groups")
        return self.api.request(method, path, label="smaregi:list_customer_groups")

    def get_product_prices(self, product_id: str) -> Response:
        method, path = self._ep("get_product_prices")
        return self.api.request(
            method,
            path.replace("{product_id}", str(product_id)),
            label="smaregi:get_prices",
            target=f"product={product_id}",
        )

    # -- 登録系 -------------------------------------------------------------
    def create_product(self, payload: dict) -> Response:
        method, path = self._ep("create_product")
        return self.api.request(
            method, path, label="smaregi:create_product", json_body=payload
        )

    def create_customer(self, payload: dict) -> Response:
        method, path = self._ep("create_customer")
        return self.api.request(
            method, path, label="smaregi:create_customer", json_body=payload
        )

    def update_product_price(
        self,
        product_id: str,
        price: int,
        *,
        price_division: int = 2,
        start_date: str,
        end_date: str | None = None,
        customer_group_id: str | None = None,
        store_id: str | None = None,
    ) -> Response:
        """商品価格を1件更新する。PoC 検証項目1・2の主対象。

        priceDivision=2 は「会員価格」、5 は「会員価格詳細」。
        顧客グループ別に価格を持てるかは customer_group_id を受け付けるか次第で、
        これは probe スクリプトで実機判定する（endpoints.yaml の note 参照）。
        """
        method, path = self._ep("update_product_price")
        body: dict[str, Any] = {
            "storeId": store_id or self.store_id,
            "priceDivision": price_division,
            "startDate": start_date,
            "price": price,
        }
        if end_date:
            body["endDate"] = end_date
        if customer_group_id is not None:
            body["customerGroupId"] = customer_group_id
        target = f"product={product_id},division={price_division}"
        if customer_group_id is not None:
            target += f",group={customer_group_id}"
        return self.api.request(
            method,
            path.replace("{product_id}", str(product_id)),
            label="smaregi:update_price",
            target=target,
            json_body=body,
        )


def _as_list(resp: Response) -> list[dict[str, Any]]:
    """スマレジは配列を直接返す場合と包む場合があるため吸収する。"""
    if not resp.ok:
        return []
    body = resp.body
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "result", "products", "customers"):
            if isinstance(body.get(key), list):
                return body[key]
    return []
