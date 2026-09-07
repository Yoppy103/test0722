#!/usr/bin/env python3
"""各スクリプトの出力を集約して、納品用の検証結果レポートを生成する。"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import base_parser, setup  # noqa: E402


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def timing_table(paths: list[Path]) -> dict[str, dict]:
    """計測CSVを読み、ラベルごとに件数と統計を再計算する。"""
    buckets: dict[str, list[float]] = {}
    fails: dict[str, int] = {}
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                label = row.get("label", "")
                ok = str(row.get("ok", "")).lower() in ("true", "1")
                if ok:
                    buckets.setdefault(label, []).append(float(row["elapsed_ms"]))
                else:
                    fails[label] = fails.get(label, 0) + 1
    out: dict[str, dict] = {}
    for label, values in buckets.items():
        values.sort()
        n = len(values)
        out[label] = {
            "count": n + fails.get(label, 0),
            "ok": n,
            "ng": fails.get(label, 0),
            "min": round(values[0], 1),
            "avg": round(sum(values) / n, 1),
            "p50": round(values[int((n - 1) * 0.5)], 1),
            "p95": round(values[int((n - 1) * 0.95)], 1),
            "max": round(values[-1], 1),
        }
    for label, count in fails.items():
        out.setdefault(label, {"count": count, "ok": 0, "ng": count})
    return out


def main() -> None:
    parser = base_parser("検証結果を集約してレポートを生成する")
    args = parser.parse_args()
    _, out_dir, _ = setup(args)

    probe = read_json(out_dir / "probe_result.json", [])
    verification = read_json(out_dir / "verification_result.json", [])
    timings = timing_table(list(out_dir.glob("*timings.csv")))

    lines = [
        "# スマレジ / Bカート API 技術検証（PoC）結果レポート",
        "",
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "> 本レポートは各検証スクリプトの実行結果を自動集計したもの。",
        "> 結論・所見は docs/02_報告書テンプレート.md に転記して仕上げる。",
        "",
        "## 1. 検証項目1: 外部APIから会員別価格（掛け率）を更新できるか",
        "",
    ]
    if probe:
        lines += ["| ベンダ | 確認項目 | 結果 | 詳細 |", "|---|---|---|---|"]
        for f in probe:
            lines.append(
                f"| {f['vendor']} | {f['item']} | **{f['result']}** | {f['detail']} |"
            )
    else:
        lines.append("_（00_probe_capabilities.py 未実行）_")

    lines += [
        "",
        "## 2. 検証項目2: 更新1件あたりの所要時間",
        "",
        "| 処理 | 件数 | 成功 | 失敗 | 最小(ms) | 平均(ms) | p50(ms) | p95(ms) | 最大(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if timings:
        for label, s in sorted(timings.items()):
            if not s.get("ok"):
                lines.append(
                    f"| {label} | {s['count']} | 0 | {s['ng']} | - | - | - | - | - |"
                )
                continue
            lines.append(
                f"| {label} | {s['count']} | {s['ok']} | {s['ng']} | {s['min']} | "
                f"{s['avg']} | {s['p50']} | {s['p95']} | {s['max']} |"
            )
    else:
        lines.append("| _（計測データなし）_ | | | | | | | | |")

    lines += [
        "",
        "**「1件」の定義（重要）**",
        "",
        "| 経路 | 1件の意味 | 20商品×3会員に必要なコール数 |",
        "|---|---|---:|",
        "| スマレジ 会員価格更新 | 商品1点 × 会員1社 | 60 |",
        "| Bカート 価格グループ掛け率 | 会員グループ1つ（全商品に波及） | 3 |",
        "| Bカート 会員ID別 個別単価 | 商品1点 × 会員1社 | 60 |",
        "",
        "> 所要時間は **API応答時間のみ**。レート制限による待機は含まない。",
        "> Bカートは 300req/300秒 の制限があり、超過すると300秒ロックされる。"
        "実運用の実効スループットはこの制限が支配的になる。",
        "",
        "## 3. 検証項目3: 会員ログイン画面への反映",
        "",
    ]
    if verification:
        total = len(verification)
        ok = sum(1 for r in verification if r.get("match"))
        by_layer: dict[str, list[dict]] = {}
        for r in verification:
            by_layer.setdefault(r.get("layer", "?"), []).append(r)
        lines += ["| レイヤ | 確認件数 | 一致 | 不一致 |", "|---|---:|---:|---:|"]
        for layer, rows in by_layer.items():
            hit = sum(1 for r in rows if r.get("match"))
            name = {"api": "API再取得での照合", "screen": "会員ログイン画面での照合"}.get(
                layer, layer
            )
            lines.append(f"| {name} | {len(rows)} | {hit} | {len(rows) - hit} |")
        lines += ["", f"**総合: 一致 {ok} / {total}**", ""]
        ng = [r for r in verification if not r.get("match")]
        if ng:
            lines += ["### 不一致の明細", ""]
            for r in ng[:50]:
                lines.append(
                    f"- {r.get('layer')} / {r.get('customerCode', r.get('login_id'))} / "
                    f"{r.get('code', r.get('productCode', '-'))}: "
                    f"期待={r.get('expected')} 実際={r.get('actual')} {r.get('error', '')}"
                )
            lines.append("")
    else:
        lines.append("_（30_verify_reflection.py 未実行）_")

    lines += [
        "",
        "## 4. 生成物一覧",
        "",
    ]
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            lines.append(f"- `out/{path.name}` ({path.stat().st_size:,} bytes)")

    report = out_dir / "REPORT.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"レポートを生成しました: {report}")


if __name__ == "__main__":
    main()
