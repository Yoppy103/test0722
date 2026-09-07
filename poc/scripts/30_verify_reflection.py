#!/usr/bin/env python3
"""検証項目3: 更新結果が会員のログイン画面に反映されているかを確認する。

2段階で確認する。両方そろって初めて「反映された」と言える。

  レイヤ1: API 再取得での照合（更新値がシステムに保存されたか）
  レイヤ2: 会員ログイン後の画面での照合（会員が実際に見る値になったか）
           → キャッシュ・バッチ反映・表示ロジックの差異はここでしか出ない

レイヤ2は HTML を取得して会員価格を抽出・照合する。ログイン方式が
Basic/フォーム/SSO のどれかは環境依存のため、フォーム認証を既定とし、
合わない場合は --skip-screen で API 照合のみに切り替えられる。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import base_parser, bcart_urls, heading, setup, smaregi_urls  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common.report import write_json  # noqa: E402


# --- レイヤ1: API 照合 -------------------------------------------------------
def verify_smaregi_api(recorder, trace, args, out_dir) -> list[dict]:
    seed_path = out_dir / "smaregi_expected_prices.json"
    if not seed_path.exists():
        print("  smaregi_expected_prices.json がないためスキップ")
        return []
    expected = json.loads(seed_path.read_text(encoding="utf-8"))

    from smaregi.client import SmaregiClient

    client = SmaregiClient(
        recorder, trace_path=trace, verbose=args.verbose, **smaregi_urls(args.mock)
    )
    client.authenticate()

    # 商品ごとに1回だけ取得して、その中から各会員グループの価格を照合する
    by_product: dict[str, list[dict]] = {}
    for row in expected:
        by_product.setdefault(row["productId"], []).append(row)

    results: list[dict] = []
    for pid, rows in by_product.items():
        resp = client.get_product_prices(pid)
        actual = resp.body if isinstance(resp.body, list) else []
        for row in rows:
            match = _find_price(actual, row["customerGroupId"])
            ok = match is not None and int(match) == int(row["expectedPrice"])
            results.append(
                {
                    "layer": "api",
                    "vendor": "smaregi",
                    "productCode": row["productCode"],
                    "customerCode": row["customerCode"],
                    "expected": row["expectedPrice"],
                    "actual": match,
                    "match": ok,
                }
            )
    _print_result("スマレジ API照合", results)
    return results


def _find_price(actual: list[dict], group_id: str) -> int | None:
    """会員価格(priceDivision=2/5) のうち、該当顧客グループのものを探す。"""
    fallback = None
    for rec in actual:
        if str(rec.get("priceDivision")) not in ("2", "5"):
            continue
        rec_group = rec.get("customerGroupId")
        if rec_group is not None and str(rec_group) == str(group_id):
            return int(rec.get("price"))
        if rec_group in (None, ""):
            fallback = int(rec.get("price"))
    # 顧客グループ別価格が使えない環境では、グループ非指定の会員価格しか無い
    return fallback


def verify_bcart_api(recorder, trace, args, out_dir) -> list[dict]:
    seed_path = out_dir / "bcart_expected_prices.json"
    if not seed_path.exists():
        print("  bcart_expected_prices.json がないためスキップ")
        return []
    expected = json.loads(seed_path.read_text(encoding="utf-8"))

    from bcart.client import BcartClient

    client = BcartClient(
        recorder, trace_path=trace, verbose=args.verbose, **bcart_urls(args.mock)
    )
    client.authenticate()

    stages = {str(s.get("stage_id")): s for s in client.list_stages()}
    results: list[dict] = []
    for row in expected:
        if row["route"] == "stage":
            # 掛け率そのものが反映されたかを確認する
            stage = next(
                (s for s in stages.values() if abs(float(s.get("rate", 0)) - row["rate"]) < 1e-9),
                None,
            )
            results.append(
                {
                    "layer": "api",
                    "vendor": "bcart",
                    "route": "stage",
                    "customerCode": row["customer_code"],
                    "expected": row["rate"],
                    "actual": stage.get("rate") if stage else None,
                    "match": stage is not None,
                }
            )
        else:
            resp = client.api.request(
                "GET",
                f"/items/{row['item_id']}/prices",
                label="bcart:get_item_prices",
                target=f"item={row['item_id']}",
            )
            rows = resp.body.get("data", []) if isinstance(resp.body, dict) else []
            # 会員ID別の個別単価なので、item_id だけでなく customer_id でも絞る。
            # ここを絞り忘れると全会員が先頭会員の価格に一致してしまう。
            actual = next(
                (
                    r.get("price")
                    for r in rows
                    if str(r.get("item_id")) == str(row["item_id"])
                    and str(r.get("customer_id")) == str(row.get("customer_id"))
                ),
                None,
            )
            results.append(
                {
                    "layer": "api",
                    "vendor": "bcart",
                    "route": "item",
                    "code": row["code"],
                    "customerCode": row["customer_code"],
                    "expected": row["expectedPrice"],
                    "actual": actual,
                    "match": actual is not None and int(actual) == int(row["expectedPrice"]),
                }
            )
    # stage 経路は同じ判定が商品数ぶん重複するので集約して見やすくする
    results = _dedupe(results)
    _print_result("Bカート API照合", results)
    return results


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("route"), r.get("code"), r.get("customerCode"))
        seen[key] = r
    return list(seen.values())


# --- レイヤ2: 会員ログイン画面での照合 ---------------------------------------
def verify_login_screen(args, out_dir) -> list[dict]:
    """会員としてログインし、表示された会員価格を期待値と突き合わせる。"""
    seed_path = out_dir / "bcart_expected_prices.json"
    if not seed_path.exists():
        print("  bcart_expected_prices.json がないためスキップ")
        return []
    expected = json.loads(seed_path.read_text(encoding="utf-8"))

    base = args.shop_url.rstrip("/")
    results: list[dict] = []

    # 会員ごとに1回ログインして商品一覧を1回取得する
    by_login: dict[str, list[dict]] = {}
    for row in expected:
        if row["route"] == "item" or args.screen_route == "stage":
            by_login.setdefault(row["login_id"], []).append(row)
    if not by_login:
        for row in expected:
            by_login.setdefault(row["login_id"], []).append(row)

    for login_id, rows in by_login.items():
        session = requests.Session()
        resp = session.post(
            f"{base}/shop/login",
            data={"login_id": login_id, "password": args.password},
            timeout=30,
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            print(f"  ログイン失敗 {login_id}: HTTP {resp.status_code}")
            results.append(
                {
                    "layer": "screen",
                    "login_id": login_id,
                    "match": False,
                    "error": f"login failed HTTP {resp.status_code}",
                }
            )
            continue

        # 反映にラグがある場合に備え、少し待ってから取得する
        if args.wait_sec:
            time.sleep(args.wait_sec)

        page = session.get(f"{base}{args.products_path}", timeout=30)
        prices = parse_member_prices(page.text)
        for row in rows:
            actual = prices.get(str(row["code"]))
            results.append(
                {
                    "layer": "screen",
                    "login_id": login_id,
                    "customerCode": row["customer_code"],
                    "code": row["code"],
                    "expected": row["expectedPrice"],
                    "actual": actual,
                    "match": actual is not None and int(actual) == int(row["expectedPrice"]),
                }
            )
        # 証跡として HTML を保存する（報告書に添付できる）
        (out_dir / f"screen_{login_id}.html").write_text(page.text, encoding="utf-8")

    _print_result("会員ログイン画面 照合", results)
    return results


ROW_RE = re.compile(
    r'<tr[^>]*data-item-code="(?P<code>[^"]+)"[^>]*>(?P<body>.*?)</tr>', re.S
)
MEMBER_PRICE_RE = re.compile(r'class="member-price"[^>]*>\s*([0-9,]+)\s*<')


def parse_member_prices(html: str) -> dict[str, int]:
    """商品一覧HTMLから 商品コード -> 会員価格 を抽出する。

    ※ セレクタは環境の HTML 構造に合わせて要調整。
      実サイトで data-item-code が無い場合は、この関数だけ差し替えれば済むよう
      抽出ロジックをここに閉じ込めてある。
    """
    out: dict[str, int] = {}
    for m in ROW_RE.finditer(html):
        price = MEMBER_PRICE_RE.search(m.group("body"))
        if price:
            out[m.group("code")] = int(price.group(1).replace(",", ""))
    return out


def _print_result(title: str, results: list[dict]) -> None:
    if not results:
        return
    ok = sum(1 for r in results if r.get("match"))
    print(f"  {title}: 一致 {ok}/{len(results)}")
    for r in results:
        if not r.get("match"):
            print(
                f"    NG {r.get('customerCode', r.get('login_id'))} "
                f"{r.get('code', r.get('productCode', ''))}: "
                f"期待={r.get('expected')} 実際={r.get('actual')} {r.get('error', '')}"
            )


def main() -> None:
    parser = base_parser("更新結果が会員のログイン画面に反映されたか確認する")
    parser.add_argument(
        "--shop-url", help="会員サイトのURL（例: https://xxx.bcart.jp）。モック時は --mock と同じ値"
    )
    parser.add_argument("--products-path", default="/shop/products")
    parser.add_argument("--password", default="PoCTest1234!")
    parser.add_argument(
        "--wait-sec", type=float, default=0, help="更新から画面確認までの待機秒数"
    )
    parser.add_argument("--screen-route", choices=["stage", "item"], default="item")
    parser.add_argument("--skip-screen", action="store_true", help="画面確認を省略")
    parser.add_argument("--skip-api", action="store_true", help="API照合を省略")
    args = parser.parse_args()
    recorder, out_dir, trace = setup(args)
    if not args.shop_url:
        args.shop_url = args.mock or ""

    results: list[dict] = []
    if not args.skip_api:
        heading("レイヤ1: API 再取得による照合")
        results += verify_smaregi_api(recorder, trace, args, out_dir)
        results += verify_bcart_api(recorder, trace, args, out_dir)

    if not args.skip_screen:
        if not args.shop_url:
            print("\n  --shop-url 未指定のため画面確認をスキップします")
        else:
            heading("レイヤ2: 会員ログイン画面での照合")
            results += verify_login_screen(args, out_dir)

    write_json(results, out_dir / "verification_result.json")

    total = len(results)
    ok = sum(1 for r in results if r.get("match"))
    heading("総合結果")
    print(f"  一致 {ok} / {total}")
    lines = [
        "# 反映確認 結果",
        "",
        f"一致 {ok} / {total}",
        "",
        "| レイヤ | 会員 | 商品 | 期待値 | 実測値 | 判定 |",
        "|---|---|---|---:|---:|:--:|",
    ]
    for r in results:
        lines.append(
            f"| {r.get('layer')} | {r.get('customerCode', r.get('login_id', ''))} | "
            f"{r.get('code', r.get('productCode', '-'))} | {r.get('expected')} | "
            f"{r.get('actual')} | {'OK' if r.get('match') else 'NG'} |"
        )
    (out_dir / "verification_result.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  {out_dir / 'verification_result.md'}")
    if ok != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
