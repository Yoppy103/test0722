#!/usr/bin/env python3
"""検証項目1の前段: 「そもそも何ができるAPIなのか」を実機に問い合わせる。

endpoints.yaml で confirmed:false としたエンドポイント/フィールドを
実際に叩いて、以下を機械的に判定する。

  - 認証が通るか
  - 各エンドポイントが存在するか（404 か否か）
  - スマレジで顧客グループ別の会員価格を持てるか（★ PoC の成否を分ける点）
  - Bカートの価格グループ（掛け率）を API から更新できるか
  - 一括更新APIが使えるか（＝所要時間の桁が変わる）

出力: out/probe_result.md / out/probe_result.json
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bcart_urls, base_parser, heading, setup, smaregi_urls  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common.report import write_json, write_csv  # noqa: E402


def probe_smaregi(recorder, trace, args) -> list[dict]:
    from smaregi.client import SmaregiClient

    findings: list[dict] = []

    def note(item, result, detail=""):
        findings.append({"vendor": "smaregi", "item": item, "result": result, "detail": detail})
        print(f"  [{result}] {item} {detail}")

    try:
        client = SmaregiClient(
            recorder, trace_path=trace, verbose=args.verbose, **smaregi_urls(args.mock)
        )
        client.authenticate()
        note("認証 (client_credentials)", "OK")
    except SystemExit as exc:
        note("認証 (client_credentials)", "NG", str(exc))
        return findings

    products = client.list_products(limit=5)
    note("商品一覧取得", "OK" if products is not None else "NG", f"{len(products)}件")

    resp = client.list_customer_groups()
    if resp.status_code == 404:
        note("顧客グループ一覧", "NG", "404 — パスが異なる可能性。要ドキュメント確認")
    else:
        note("顧客グループ一覧", "OK" if resp.ok else "NG", f"HTTP {resp.status_code}")

    if not products:
        note("会員価格の更新可否", "SKIP", "商品が0件。先に 10_seed_smaregi.py を実行")
        return findings

    pid = str(products[0].get("productId"))
    today = date.today().isoformat()

    # (a) 会員価格（顧客グループ指定なし）が入るか
    r = client.update_product_price(pid, 1000, price_division=2, start_date=today)
    note(
        "会員価格 priceDivision=2 の更新",
        "OK" if r.ok else "NG",
        f"HTTP {r.status_code}",
    )

    # (b) ★ 顧客グループ別の会員価格が入るか = 「会員別価格」が実現できるか
    r = client.update_product_price(
        pid, 900, price_division=2, start_date=today, customer_group_id="1"
    )
    if r.ok:
        note(
            "★顧客グループ別 会員価格",
            "OK",
            "customerGroupId が受理された → 会員別価格をスマレジ単体で実現可能",
        )
    else:
        note(
            "★顧客グループ別 会員価格",
            "NG",
            f"HTTP {r.status_code} — スマレジ単体では会員別価格を持てない可能性。"
            "Bカート側で会員別価格を持つ構成を検討（docs/01_API調査メモ.md 参照）",
        )

    # (c) 一括更新APIの有無（所要時間に直結）
    try:
        method, path = client._ep("bulk_update_product_prices")
        r = client.api.request(
            method,
            path,
            label="smaregi:probe_bulk",
            json_body=[
                {
                    "productId": pid,
                    "storeId": client.store_id,
                    "priceDivision": 2,
                    "startDate": today,
                    "price": 950,
                }
            ],
        )
        note(
            "一括価格更新API",
            "OK" if r.ok else "NG",
            f"HTTP {r.status_code}"
            + ("" if r.ok else " — 存在しなければ1件ずつ更新にフォールバック"),
        )
    except Exception as exc:  # noqa: BLE001
        note("一括価格更新API", "NG", str(exc))

    return findings


def probe_bcart(recorder, trace, args) -> list[dict]:
    from bcart.client import BcartClient

    findings: list[dict] = []

    def note(item, result, detail=""):
        findings.append({"vendor": "bcart", "item": item, "result": result, "detail": detail})
        print(f"  [{result}] {item} {detail}")

    try:
        client = BcartClient(
            recorder, trace_path=trace, verbose=args.verbose, **bcart_urls(args.mock)
        )
        client.authenticate()
        note("認証", "OK")
    except SystemExit as exc:
        note("認証", "NG", str(exc))
        return findings

    items = client.list_items(limit=5)
    note("商品一覧取得", "OK", f"{len(items)}件")

    customers = client.list_customers(limit=5)
    note("会員一覧取得", "OK", f"{len(customers)}件")

    stages = client.list_stages()
    note("価格グループ一覧", "OK" if stages else "NG", f"{len(stages)}件")

    if stages:
        sid = str(stages[0].get("stage_id") or stages[0].get("id"))
        original = stages[0].get("rate")
        r = client.update_stage_rate(sid, 0.85)
        note(
            "★価格グループの掛け率更新",
            "OK" if r.ok else "NG",
            f"HTTP {r.status_code}"
            + (" → グループ単位の掛け率を API から変更可能" if r.ok else ""),
        )
        # 検証で汚さないよう元に戻す
        if r.ok and original is not None:
            client.update_stage_rate(sid, float(original))

    if items and customers:
        iid = str(items[0].get("item_id") or items[0].get("id"))
        cid = str(customers[0].get("customer_id") or customers[0].get("id"))
        r = client.update_item_price(iid, cid, 1234)
        note(
            "★会員ID別 個別単価の更新",
            "OK" if r.ok else "NG",
            f"HTTP {r.status_code}",
        )

    return findings


def main() -> None:
    parser = base_parser("スマレジ/Bカート APIの実現可能性を実機で判定する")
    parser.add_argument(
        "--vendor", choices=["smaregi", "bcart", "both"], default="both"
    )
    args = parser.parse_args()
    recorder, out_dir, trace = setup(args)

    findings: list[dict] = []
    if args.vendor in ("smaregi", "both"):
        heading("スマレジ 能力調査")
        findings += probe_smaregi(recorder, trace, args)
    if args.vendor in ("bcart", "both"):
        heading("Bカート 能力調査")
        findings += probe_bcart(recorder, trace, args)

    write_json(findings, out_dir / "probe_result.json")
    write_csv(recorder, out_dir / "probe_timings.csv")

    lines = ["# API 能力調査結果", "", "| ベンダ | 確認項目 | 結果 | 詳細 |", "|---|---|---|---|"]
    for f in findings:
        lines.append(
            f"| {f['vendor']} | {f['item']} | {f['result']} | {f['detail']} |"
        )
    ng = [f for f in findings if f["result"] == "NG"]
    lines += ["", f"NG: {len(ng)} 件 / 全 {len(findings)} 件", ""]
    (out_dir / "probe_result.md").write_text("\n".join(lines), encoding="utf-8")

    heading("完了")
    print(f"  {out_dir / 'probe_result.md'}")
    print(f"  {out_dir / 'probe_result.json'}")
    if ng:
        print(f"\n  ★ NG が {len(ng)} 件あります。報告書の「制約事項」に転記してください。")


if __name__ == "__main__":
    main()
