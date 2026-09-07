#!/usr/bin/env python3
"""検証項目1+2（Bカート）: 会員別価格（掛け率）を更新し所要時間を計測する。

Bカートは2経路あり、「1件あたり」の意味が全く違うので必ず分けて計測する:

  経路A: 価格グループの掛け率を更新   … 1コールで「会員1社 × 全商品」に効く
  経路B: 会員ID別の個別単価を更新     … 1コールで「会員1社 × 商品1点」

同じ「更新1件」でも A は3コール、B は60コール。
所要時間の報告では、この定義差が結論を左右するため必ず両方を出す。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import base_parser, bcart_urls, heading, setup  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import dummy_data  # noqa: E402
from common.report import write_csv, write_json, write_summary_md  # noqa: E402


def main() -> None:
    parser = base_parser("Bカートの会員別価格（掛け率）を更新し所要時間を計測する")
    parser.add_argument(
        "--mode",
        choices=["stage", "item", "both"],
        default="both",
        help="stage=価格グループ掛け率, item=会員ID別個別単価",
    )
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    recorder, out_dir, trace = setup(args)

    seed_path = out_dir / "bcart_seed.json"
    if not seed_path.exists():
        raise SystemExit(
            f"{seed_path} がありません。先に 11_seed_bcart.py を実行してください。"
        )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    items, customers = seed["items"], seed["customers"]
    if not items or not customers:
        raise SystemExit("投入済みの商品または会員が0件です。")

    from bcart.client import BcartClient

    client = BcartClient(
        recorder, trace_path=trace, verbose=args.verbose, **bcart_urls(args.mock)
    )
    client.authenticate()

    expected: list[dict] = []

    # --- 経路A: 価格グループの掛け率 ---------------------------------------
    if args.mode in ("stage", "both"):
        heading(f"経路A: 価格グループの掛け率を更新（{len(customers)}グループ）")
        for _ in range(args.repeat):
            for cust in customers:
                # 掛け率を意図的に 5% 下げて「更新されたこと」を判別可能にする
                new_rate = round(float(cust["rate"]) - 0.05, 2)
                resp = client.update_stage_rate(cust["stage_id"], new_rate)
                status = "OK" if resp.ok else f"NG HTTP {resp.status_code}"
                print(
                    f"  stage={cust['stage_id']} ({cust['code']}) "
                    f"rate {cust['rate']} -> {new_rate} : {status}"
                )
                if not resp.ok:
                    print(f"    {resp.body}")
                for item in items:
                    expected.append(
                        {
                            "route": "stage",
                            "item_id": item["item_id"],
                            "code": item["code"],
                            "customer_code": cust["code"],
                            "login_id": cust["login_id"],
                            "listPrice": item["listPrice"],
                            "rate": new_rate,
                            "expectedPrice": dummy_data.apply_rate(
                                int(item["listPrice"]), new_rate
                            ),
                            "updateOk": resp.ok,
                        }
                    )
        s = recorder.summary("bcart:update_stage_rate")
        if s.get("ok_count"):
            print(
                f"  1件(=1グループ)あたり: 平均 {s['avg_ms']}ms / p95 {s['p95_ms']}ms"
            )

    # --- 経路B: 会員ID別の個別単価 -----------------------------------------
    if args.mode in ("item", "both"):
        total = len(items) * len(customers) * args.repeat
        heading(f"経路B: 会員ID別の個別単価を更新（{total}件）")
        done = 0
        for _ in range(args.repeat):
            for cust in customers:
                rate = float(cust["rate"])
                for item in items:
                    price = dummy_data.apply_rate(int(item["listPrice"]), rate)
                    resp = client.update_item_price(
                        item["item_id"], cust["customer_id"], price
                    )
                    done += 1
                    if not resp.ok:
                        print(
                            f"  NG item={item['code']} customer={cust['code']}: "
                            f"HTTP {resp.status_code} {resp.body}"
                        )
                    expected.append(
                        {
                            "route": "item",
                            "item_id": item["item_id"],
                            "code": item["code"],
                            "customer_code": cust["code"],
                            "customer_id": cust["customer_id"],
                            "login_id": cust["login_id"],
                            "listPrice": item["listPrice"],
                            "rate": rate,
                            "expectedPrice": price,
                            "updateOk": resp.ok,
                        }
                    )
                    if done % 10 == 0:
                        print(f"  {done}/{total} 件完了")
        s = recorder.summary("bcart:update_item_price")
        if s.get("ok_count"):
            print(
                f"  1件(=商品1点×会員1社)あたり: 平均 {s['avg_ms']}ms / p95 {s['p95_ms']}ms"
            )

    rl = client.spec["rate_limit"]
    write_json(expected, out_dir / "bcart_expected_prices.json")
    write_csv(recorder, out_dir / "bcart_update_timings.csv")
    write_summary_md(
        recorder,
        out_dir / "bcart_update_summary.md",
        title="Bカート 会員別価格（掛け率） 更新 計測結果",
        context={
            "対象": f"商品{len(items)}点 × 会員{len(customers)}社 × {args.repeat}回",
            "経路": args.mode,
            "経路Aの1件": "価格グループ1つの掛け率更新（全商品に波及）",
            "経路Bの1件": "商品1点 × 会員1社 の個別単価更新",
            "レート制限": f"{rl['max_requests']}回 / {rl['window_sec']}秒"
            f"（超過で{rl['window_sec']}秒ロック）",
            "接続先": "モック" if args.mock else "トライアル環境",
        },
    )
    heading("完了")
    print(f"  {out_dir / 'bcart_update_summary.md'}")


if __name__ == "__main__":
    main()
