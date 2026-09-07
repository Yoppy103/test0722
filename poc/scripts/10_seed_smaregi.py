#!/usr/bin/env python3
"""スマレジにダミーデータ（商品20点・会員3社）を投入する。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import base_parser, heading, setup, smaregi_urls  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import dummy_data  # noqa: E402
from common.report import write_csv, write_json  # noqa: E402


def main() -> None:
    parser = base_parser("スマレジへダミーデータを投入する")
    parser.add_argument("--products", type=int, default=20)
    args = parser.parse_args()
    recorder, out_dir, trace = setup(args)

    from smaregi.client import SmaregiClient

    client = SmaregiClient(
        recorder, trace_path=trace, verbose=args.verbose, **smaregi_urls(args.mock)
    )
    client.authenticate()

    heading(f"商品を {args.products} 点登録")
    products = []
    for p in dummy_data.products(args.products):
        resp = client.create_product(
            {
                "productCode": p.code,
                "productName": p.name,
                "price": str(p.list_price),
                "taxDivision": "1",
                "productDivision": "1",
            }
        )
        if resp.ok:
            products.append(
                {
                    "productId": str(resp.body.get("productId")),
                    "productCode": p.code,
                    "listPrice": p.list_price,
                }
            )
        else:
            print(f"  NG {p.code}: HTTP {resp.status_code} {resp.body}")
    print(f"  登録成功: {len(products)} / {args.products}")

    heading("会員を 3 社登録")
    customers = []
    for i, c in enumerate(dummy_data.customers(), start=1):
        resp = client.create_customer(
            {
                "customerCode": c.code,
                "lastName": c.name,
                "customerGroupId": str(i),  # 1社=1顧客グループとして掛け率を紐付ける
            }
        )
        if resp.ok:
            customers.append(
                {
                    "customerId": str(resp.body.get("customerId")),
                    "customerCode": c.code,
                    "customerGroupId": str(i),
                    "rate": c.rate,
                }
            )
        else:
            print(f"  NG {c.code}: HTTP {resp.status_code} {resp.body}")
    print(f"  登録成功: {len(customers)} / 3")

    # 後続スクリプトが ID を引き継ぐための受け渡しファイル
    write_json(
        {"products": products, "customers": customers},
        out_dir / "smaregi_seed.json",
    )
    write_csv(recorder, out_dir / "smaregi_seed_timings.csv")
    heading("完了")
    print(f"  {out_dir / 'smaregi_seed.json'}")


if __name__ == "__main__":
    main()
