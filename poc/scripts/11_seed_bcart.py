#!/usr/bin/env python3
"""Bカートにダミーデータ（商品20点・会員3社・価格グループ3つ）を投入する。

Bカートは管理画面からの初期登録が前提の項目もあるため、
API で作れないものは「手動で作る前提」として警告を出し、処理は続行する。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import base_parser, bcart_urls, heading, setup  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import dummy_data  # noqa: E402
from common.report import write_csv, write_json  # noqa: E402


def main() -> None:
    parser = base_parser("Bカートへダミーデータを投入する")
    parser.add_argument("--products", type=int, default=20)
    args = parser.parse_args()
    recorder, out_dir, trace = setup(args)

    from bcart.client import BcartClient

    client = BcartClient(
        recorder, trace_path=trace, verbose=args.verbose, **bcart_urls(args.mock)
    )
    client.authenticate()

    heading("価格グループ（ステージ）を確認")
    stages = client.list_stages()
    if not stages:
        print(
            "  価格グループが取得できません。Bカート管理画面で "
            "「価格グループ」を3つ作成してから再実行してください。"
        )
    for s in stages:
        print(f"  stage_id={s.get('stage_id')} name={s.get('name')} rate={s.get('rate')}")

    heading(f"商品を {args.products} 点登録")
    items = []
    for p in dummy_data.products(args.products):
        resp = client.api.request(
            "POST",
            "/items",
            label="bcart:create_item",
            json_body={"code": p.code, "name": p.name, "price": p.list_price},
        )
        if resp.ok:
            items.append(
                {
                    "item_id": str(resp.body.get("item_id")),
                    "code": p.code,
                    "listPrice": p.list_price,
                }
            )
        else:
            print(f"  NG {p.code}: HTTP {resp.status_code} {resp.body}")
    print(f"  登録成功: {len(items)} / {args.products}")

    heading("会員を 3 社登録")
    customers = []
    for i, c in enumerate(dummy_data.customers(), start=1):
        resp = client.api.request(
            "POST",
            "/customers",
            label="bcart:create_customer",
            json_body={
                "code": c.code,
                "name": c.name,
                "stage_id": str(i),
                "login_id": c.code.lower(),
                "password": "PoCTest1234!",
            },
        )
        if resp.ok:
            customers.append(
                {
                    "customer_id": str(resp.body.get("customer_id")),
                    "code": c.code,
                    "stage_id": str(i),
                    "rate": c.rate,
                    "login_id": c.code.lower(),
                }
            )
        else:
            print(f"  NG {c.code}: HTTP {resp.status_code} {resp.body}")
    print(f"  登録成功: {len(customers)} / 3")

    write_json(
        {"items": items, "customers": customers, "stages": stages},
        out_dir / "bcart_seed.json",
    )
    write_csv(recorder, out_dir / "bcart_seed_timings.csv")
    heading("完了")
    print(f"  {out_dir / 'bcart_seed.json'}")
    print("  ※ ログインパスワードは検証用の固定値。実データでは絶対に使わないこと。")


if __name__ == "__main__":
    main()
