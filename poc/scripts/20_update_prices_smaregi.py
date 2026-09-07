#!/usr/bin/env python3
"""検証項目1+2（スマレジ）: 会員別価格を外部APIで更新し、1件あたりの時間を計測する。

「1件」の定義を明示しておく（報告書で必ず併記すること）:
  1件 = 商品1点 × 会員1社 の会員価格を1回更新するAPIコール
  → 商品20点 × 会員3社 = 60件
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import base_parser, heading, setup, smaregi_urls  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import dummy_data  # noqa: E402
from common.report import write_csv, write_json, write_summary_md  # noqa: E402


def main() -> None:
    parser = base_parser("スマレジの会員別価格を更新し所要時間を計測する")
    parser.add_argument(
        "--price-division",
        type=int,
        default=2,
        help="価格区分。2=会員価格, 5=会員価格詳細",
    )
    parser.add_argument(
        "--no-group",
        action="store_true",
        help="customerGroupId を送らない（顧客グループ別価格が使えない環境用）",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="計測を安定させるための繰り返し回数"
    )
    parser.add_argument(
        "--abort-after",
        type=int,
        default=5,
        help="同一エラーがこの件数連続したら中断する（環境側の制約を早期に検知）",
    )
    args = parser.parse_args()
    recorder, out_dir, trace = setup(args)

    seed_path = out_dir / "smaregi_seed.json"
    if not seed_path.exists():
        raise SystemExit(
            f"{seed_path} がありません。先に 10_seed_smaregi.py を実行してください。"
        )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    products, customers = seed["products"], seed["customers"]
    if not products or not customers:
        raise SystemExit("投入済みの商品または会員が0件です。")

    from smaregi.client import SmaregiClient

    client = SmaregiClient(
        recorder, trace_path=trace, verbose=args.verbose, **smaregi_urls(args.mock)
    )
    client.authenticate()

    today = date.today().isoformat()
    total = len(products) * len(customers) * args.repeat
    heading(
        f"会員別価格を更新: 商品{len(products)}点 × 会員{len(customers)}社 "
        f"× {args.repeat}回 = {total}件"
    )

    expected: list[dict] = []
    ok_count = 0
    done = 0
    consecutive_fail = 0
    aborted = False
    for _ in range(args.repeat):
        for cust in customers:
            rate = float(cust["rate"])
            for prod in products:
                member_price = dummy_data.apply_rate(int(prod["listPrice"]), rate)
                resp = client.update_product_price(
                    prod["productId"],
                    member_price,
                    price_division=args.price_division,
                    start_date=today,
                    customer_group_id=None if args.no_group else cust["customerGroupId"],
                )
                done += 1
                if resp.ok:
                    ok_count += 1
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1
                    # 同じエラーが延々続くのは環境側の制約（未対応フィールド等）。
                    # 60件叩き切っても得られる情報は増えないので早期に打ち切る。
                    if consecutive_fail <= 3:
                        print(
                            f"  NG product={prod['productCode']} "
                            f"customer={cust['customerCode']}: "
                            f"HTTP {resp.status_code} {resp.body}"
                        )
                expected.append(
                    {
                        "productId": prod["productId"],
                        "productCode": prod["productCode"],
                        "customerCode": cust["customerCode"],
                        "customerGroupId": cust["customerGroupId"],
                        "listPrice": prod["listPrice"],
                        "rate": rate,
                        "expectedPrice": member_price,
                        "updateOk": resp.ok,
                    }
                )
                if done % 10 == 0:
                    print(f"  {done}/{total} 件完了")

                if consecutive_fail >= args.abort_after:
                    print(
                        f"\n  同一エラーが {consecutive_fail} 件連続したため中断しました"
                        f"（{done}/{total} 件時点）。"
                    )
                    if not args.no_group:
                        print(
                            "  → customerGroupId が原因の可能性があります。"
                            "--no-group を付けて再実行し、顧客グループを指定しない"
                            "会員価格なら通るかを切り分けてください。"
                        )
                    aborted = True
                    break
            if aborted:
                break
        if aborted:
            break

    summary = recorder.summary("smaregi:update_price")
    heading("計測結果")
    print(f"  成功 {ok_count}/{done} 件（計画 {total} 件）")
    if summary.get("ok_count"):
        print(
            f"  1件あたり: 平均 {summary['avg_ms']}ms / "
            f"p50 {summary['p50_ms']}ms / p95 {summary['p95_ms']}ms / "
            f"最大 {summary['max_ms']}ms"
        )
        est = summary["avg_ms"] * total / 1000.0
        print(f"  {total}件の純API時間 合計見込み: 約 {est:.1f} 秒")
    if aborted:
        print("  ※ 中断したため、計測値は全件を代表しません。")

    write_json(expected, out_dir / "smaregi_expected_prices.json")
    write_csv(recorder, out_dir / "smaregi_update_timings.csv")
    write_summary_md(
        recorder,
        out_dir / "smaregi_update_summary.md",
        title="スマレジ 会員別価格 更新 計測結果",
        context={
            "対象": f"商品{len(products)}点 × 会員{len(customers)}社 × {args.repeat}回",
            "更新件数": f"{done}（計画 {total}）",
            "成功件数": ok_count,
            "中断": "あり（同一エラーが連続）" if aborted else "なし",
            "価格区分 (priceDivision)": args.price_division,
            "顧客グループ指定": "なし" if args.no_group else "あり (customerGroupId)",
            "接続先": "モック" if args.mock else "トライアル環境",
            "1件の定義": "商品1点 × 会員1社 の会員価格を1回更新するAPIコール",
        },
    )
    heading("完了")
    print(f"  {out_dir / 'smaregi_update_summary.md'}")


if __name__ == "__main__":
    main()
