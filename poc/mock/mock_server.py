#!/usr/bin/env python3
"""スマレジ / Bカート API と「会員ログイン画面」のモックサーバ。

用途:
  1. トライアル環境の払い出し前でも、スクリプト一式を通しで動作確認できる
  2. 本番トライアルに投げる前のドライランで、リクエスト内容を目視確認できる
  3. 「顧客グループ別価格が使えない」等の失敗シナリオを再現し、
     スクリプトのフォールバック動作を検証できる

これは検証用のスタブであり、実 API の完全な再現ではない。
挙動は環境変数で切り替える:
  MOCK_SMAREGI_GROUP_PRICE=off  … 顧客グループ別価格を 400 で拒否（最悪ケース再現）
  MOCK_SMAREGI_BULK=off         … 一括更新APIを 404 にする
  MOCK_LATENCY_MS=80            … 1リクエストあたりの疑似レイテンシ中央値
  MOCK_BCART_RATE_LIMIT=on      … Bカートのレート制限(429)を再現

起動: python3 mock/mock_server.py --port 8899
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LATENCY_MS = int(os.environ.get("MOCK_LATENCY_MS", "80"))
GROUP_PRICE_ENABLED = os.environ.get("MOCK_SMAREGI_GROUP_PRICE", "on") != "off"
BULK_ENABLED = os.environ.get("MOCK_SMAREGI_BULK", "on") != "off"
BCART_RATE_LIMIT = os.environ.get("MOCK_BCART_RATE_LIMIT", "off") == "on"

LOCK = threading.Lock()

# --- モックの内部状態 --------------------------------------------------------
STATE: dict = {
    "smaregi": {
        "products": {},        # productId -> product
        "customers": {},       # customerId -> customer
        "customer_groups": {
            "1": {"customerGroupId": "1", "customerGroupName": "検証商事株式会社"},
            "2": {"customerGroupId": "2", "customerGroupName": "テスト物産株式会社"},
            "3": {"customerGroupId": "3", "customerGroupName": "サンプル流通株式会社"},
        },
        "prices": {},          # (productId, division, groupId) -> price record
        "seq": 1000,
    },
    "bcart": {
        "items": {},
        "customers": {},
        "stages": {
            "1": {"stage_id": "1", "name": "Aグループ", "rate": 0.80},
            "2": {"stage_id": "2", "name": "Bグループ", "rate": 0.75},
            "3": {"stage_id": "3", "name": "Cグループ", "rate": 0.70},
        },
        "item_prices": {},     # (item_id, customer_id) -> price
        "requests": [],        # レート制限判定用のタイムスタンプ列
    },
    "sessions": {},            # cookie -> customer_id
}


def latency() -> None:
    """実 API に近い揺らぎを与える。計測スクリプトの妥当性確認のため。"""
    if LATENCY_MS <= 0:
        return
    time.sleep(random.uniform(LATENCY_MS * 0.6, LATENCY_MS * 1.6) / 1000.0)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A002 - 標準ログを静かにする
        if os.environ.get("MOCK_VERBOSE"):
            super().log_message(fmt, *args)

    # -- 共通ヘルパ ---------------------------------------------------------
    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, html: str, cookie: str | None = None) -> None:
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", f"poc_session={cookie}; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def _authed(self) -> bool:
        return self.headers.get("Authorization", "").startswith("Bearer ")

    # -- ルーティング -------------------------------------------------------
    def do_GET(self):  # noqa: N802
        self._route("GET")

    def do_POST(self):  # noqa: N802
        self._route("POST")

    def do_PATCH(self):  # noqa: N802
        self._route("PATCH")

    def do_PUT(self):  # noqa: N802
        self._route("PUT")

    def _route(self, method: str):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        body = self._read_body()
        latency()
        try:
            with LOCK:
                if path.startswith("/shop"):
                    return self._shop(method, path, body)
                if "/token" in path or path.startswith("/oauth"):
                    return self._token(method, path, body)
                if "/pos/" in path or path.endswith("/pos"):
                    return self._smaregi(method, path, query, body)
                if path.startswith("/v1/"):
                    return self._bcart(method, path, query, body)
            return self._json(404, {"message": f"no mock route: {method} {path}"})
        except BrokenPipeError:
            return None

    # -- 認証 ---------------------------------------------------------------
    def _token(self, method: str, path: str, body):
        if method != "POST":
            return self._json(405, {"message": "method not allowed"})
        vendor = "bcart" if path.startswith("/oauth") else "smaregi"
        return self._json(
            200,
            {
                "access_token": f"mock-token-{vendor}-{int(time.time())}",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": body.get("scope", ""),
            },
        )

    # -- スマレジ -----------------------------------------------------------
    def _smaregi(self, method: str, path: str, query, body):
        if not self._authed():
            return self._json(401, {"message": "Unauthorized"})
        s = STATE["smaregi"]
        tail = path.split("/pos", 1)[1] or "/"

        if tail == "/stores" and method == "GET":
            return self._json(200, [{"storeId": "1", "storeName": "PoC検証店舗"}])

        if tail == "/customer_groups" and method == "GET":
            return self._json(200, list(s["customer_groups"].values()))

        if tail == "/products" and method == "GET":
            return self._json(200, list(s["products"].values()))

        if tail == "/products" and method == "POST":
            s["seq"] += 1
            pid = str(s["seq"])
            product = {
                "productId": pid,
                "productCode": body.get("productCode", ""),
                "productName": body.get("productName", ""),
                "price": body.get("price", "0"),
            }
            s["products"][pid] = product
            return self._json(200, product)

        if tail == "/customers" and method == "GET":
            return self._json(200, list(s["customers"].values()))

        if tail == "/customers" and method == "POST":
            s["seq"] += 1
            cid = str(s["seq"])
            customer = {
                "customerId": cid,
                "customerCode": body.get("customerCode", ""),
                "customerGroupId": body.get("customerGroupId"),
                "lastName": body.get("lastName", ""),
            }
            s["customers"][cid] = customer
            return self._json(200, customer)

        # 一括更新（存在有無を切り替えられる）
        if tail == "/products/prices/bulk":
            if not BULK_ENABLED:
                return self._json(404, {"message": "Not Found"})
            if method != "POST":
                return self._json(405, {"message": "method not allowed"})
            rows = body if isinstance(body, list) else body.get("prices", [])
            for row in rows:
                self._store_price(row.get("productId"), row)
            return self._json(200, {"updated": len(rows)})

        m = re.fullmatch(r"/products/([^/]+)/prices", tail)
        if m:
            pid = m.group(1)
            if method == "GET":
                out = [
                    v for k, v in s["prices"].items() if k[0] == pid
                ]
                return self._json(200, out)
            if method in ("POST", "PATCH", "PUT"):
                group_id = body.get("customerGroupId")
                # 「顧客グループ別価格が使えない」最悪ケースの再現
                if group_id is not None and not GROUP_PRICE_ENABLED:
                    return self._json(
                        400,
                        {
                            "message": "customerGroupId is not supported",
                            "code": "E_UNSUPPORTED_FIELD",
                        },
                    )
                rec = self._store_price(pid, body)
                return self._json(200, rec)

        return self._json(404, {"message": f"no mock route: {method} {path}"})

    def _store_price(self, product_id, body) -> dict:
        s = STATE["smaregi"]
        key = (
            str(product_id),
            str(body.get("priceDivision", 1)),
            str(body.get("customerGroupId") or ""),
        )
        rec = {
            "productId": str(product_id),
            "storeId": str(body.get("storeId", "1")),
            "priceDivision": str(body.get("priceDivision", 1)),
            "customerGroupId": body.get("customerGroupId"),
            "startDate": body.get("startDate"),
            "endDate": body.get("endDate"),
            "price": str(body.get("price")),
        }
        s["prices"][key] = rec
        return rec

    # -- Bカート -------------------------------------------------------------
    def _bcart(self, method: str, path: str, query, body):
        if not self._authed():
            return self._json(401, {"message": "Unauthorized"})
        b = STATE["bcart"]

        if BCART_RATE_LIMIT:
            now = time.time()
            b["requests"] = [t for t in b["requests"] if now - t < 300]
            b["requests"].append(now)
            if len(b["requests"]) > 300:
                self.send_response(429)
                self.send_header("Retry-After", "300")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None

        tail = path[3:]  # strip "/v1"

        if tail == "/items" and method == "GET":
            return self._json(200, {"data": list(b["items"].values())})
        if tail == "/items" and method == "POST":
            item_id = body.get("code") or str(len(b["items"]) + 1)
            item = {
                "item_id": item_id,
                "code": body.get("code"),
                "name": body.get("name"),
                "price": body.get("price"),
            }
            b["items"][item_id] = item
            return self._json(200, item)

        if tail == "/customers" and method == "GET":
            return self._json(200, {"data": list(b["customers"].values())})
        if tail == "/customers" and method == "POST":
            cid = body.get("code") or str(len(b["customers"]) + 1)
            customer = {
                "customer_id": cid,
                "code": body.get("code"),
                "name": body.get("name"),
                "stage_id": body.get("stage_id", "1"),
                "login_id": body.get("login_id", cid),
                "password": body.get("password", "poc-pass"),
            }
            b["customers"][cid] = customer
            return self._json(200, customer)

        if tail == "/stages" and method == "GET":
            return self._json(200, {"data": list(b["stages"].values())})

        m = re.fullmatch(r"/stages/([^/]+)", tail)
        if m and method in ("PATCH", "PUT"):
            sid = m.group(1)
            if sid not in b["stages"]:
                return self._json(404, {"message": "stage not found"})
            if "rate" in body:
                b["stages"][sid]["rate"] = float(body["rate"])
            return self._json(200, b["stages"][sid])

        m = re.fullmatch(r"/customers/([^/]+)", tail)
        if m and method in ("PATCH", "PUT"):
            cid = m.group(1)
            if cid not in b["customers"]:
                return self._json(404, {"message": "customer not found"})
            b["customers"][cid].update(
                {k: v for k, v in body.items() if k in ("stage_id", "name")}
            )
            return self._json(200, b["customers"][cid])

        m = re.fullmatch(r"/items/([^/]+)/prices", tail)
        if m:
            item_id = m.group(1)
            if method == "GET":
                out = [
                    {"item_id": k[0], "customer_id": k[1], "price": v}
                    for k, v in b["item_prices"].items()
                    if k[0] == item_id
                ]
                return self._json(200, {"data": out})
            if method in ("PATCH", "PUT", "POST"):
                cust = str(body.get("customer_id"))
                b["item_prices"][(item_id, cust)] = int(body.get("price"))
                return self._json(
                    200,
                    {"item_id": item_id, "customer_id": cust, "price": body.get("price")},
                )

        return self._json(404, {"message": f"no mock route: {method} {path}"})

    # -- 会員ログイン画面（検証項目3のスタブ） -------------------------------
    def _shop(self, method: str, path: str, body):
        b = STATE["bcart"]
        if path == "/shop/login" and method == "GET":
            return self._html(200, LOGIN_HTML)

        if path == "/shop/login" and method == "POST":
            login_id = str(body.get("login_id", ""))
            password = str(body.get("password", ""))
            for cust in b["customers"].values():
                if (
                    str(cust.get("login_id")) == login_id
                    and str(cust.get("password")) == password
                ):
                    token = f"sess-{login_id}-{int(time.time())}"
                    STATE["sessions"][token] = cust["customer_id"]
                    return self._html(
                        200, '<p>ログイン成功</p><a href="/shop/products">商品一覧</a>',
                        cookie=token,
                    )
            return self._html(401, "<p>ログイン失敗</p>")

        if path == "/shop/products" and method == "GET":
            cookie = self.headers.get("Cookie", "")
            token = ""
            for part in cookie.split(";"):
                if part.strip().startswith("poc_session="):
                    token = part.strip().split("=", 1)[1]
            cid = STATE["sessions"].get(token)
            if not cid:
                return self._html(401, "<p>未ログイン</p>")
            cust = b["customers"].get(cid, {})
            stage = b["stages"].get(str(cust.get("stage_id", "1")), {"rate": 1.0})
            rows = []
            for item in b["items"].values():
                iid = str(item["item_id"])
                # 個別単価があれば優先。なければ 定価 x グループ掛け率。
                individual = b["item_prices"].get((iid, str(cid)))
                if individual is not None:
                    price, source = individual, "個別単価"
                else:
                    price = int(int(item.get("price", 0)) * float(stage["rate"]))
                    source = f"掛け率 {stage['rate']}"
                rows.append(
                    f'<tr data-item-code="{item.get("code")}">'
                    f'<td class="code">{item.get("code")}</td>'
                    f'<td class="name">{item.get("name")}</td>'
                    f'<td class="list-price">{item.get("price")}</td>'
                    f'<td class="member-price">{price}</td>'
                    f'<td class="source">{source}</td></tr>'
                )
            html = PRODUCTS_HTML.format(
                customer=cust.get("name", ""),
                stage=stage.get("name", ""),
                rows="\n".join(rows),
            )
            return self._html(200, html)

        return self._html(404, "<p>not found</p>")


LOGIN_HTML = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>PoC 会員ログイン</title>
<h1>会員ログイン（モック）</h1>
<form method="post" action="/shop/login">
<input name="login_id" placeholder="ログインID">
<input name="password" type="password" placeholder="パスワード">
<button type="submit">ログイン</button>
</form></html>"""

PRODUCTS_HTML = """<!doctype html><html lang="ja"><meta charset="utf-8">
<title>会員向け商品一覧</title>
<h1>会員向け商品一覧（モック）</h1>
<p id="customer-name">{customer}</p>
<p id="stage-name">{stage}</p>
<table id="product-table">
<thead><tr><th>商品コード</th><th>商品名</th><th>定価</th><th>会員価格</th><th>根拠</th></tr></thead>
<tbody>
{rows}
</tbody></table></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock server listening on http://{args.host}:{args.port}")
    print(
        f"  smaregi group price: {'ON' if GROUP_PRICE_ENABLED else 'OFF (400を返す)'}\n"
        f"  smaregi bulk api   : {'ON' if BULK_ENABLED else 'OFF (404を返す)'}\n"
        f"  bcart rate limit   : {'ON' if BCART_RATE_LIMIT else 'OFF'}\n"
        f"  latency            : {LATENCY_MS}ms"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
