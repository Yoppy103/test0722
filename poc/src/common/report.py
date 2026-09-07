"""計測結果を CSV / Markdown で書き出す。そのまま納品物になる粒度で出す。"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .timing import Recorder


def write_csv(recorder: Recorder, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [m.as_row() for m in recorder.measurements]
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_summary_md(
    recorder: Recorder, path: Path, *, title: str, context: dict[str, Any]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {title}",
        "",
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 実行条件",
        "",
    ]
    for key, value in context.items():
        lines.append(f"- **{key}**: {value}")

    lines += [
        "",
        "## 計測結果（処理種別ごと）",
        "",
        "| 処理 | 件数 | 成功 | 失敗 | 最小(ms) | 平均(ms) | p50(ms) | p95(ms) | 最大(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in recorder.labels():
        s = recorder.summary(label)
        if not s.get("ok_count"):
            lines.append(
                f"| {label} | {s['count']} | 0 | {s['count']} | - | - | - | - | - |"
            )
            continue
        lines.append(
            f"| {label} | {s['count']} | {s['ok_count']} | {s['ng_count']} | "
            f"{s['min_ms']} | {s['avg_ms']} | {s['p50_ms']} | {s['p95_ms']} | {s['max_ms']} |"
        )

    throttle = sum(m.throttle_wait_ms for m in recorder.measurements)
    lines += [
        "",
        "> 上表の所要時間は **API 応答時間のみ**。レート制限による待機時間は含めない。",
        f"> 本実行のレート制限待機の合計: **{throttle / 1000:.1f} 秒**",
        "",
    ]

    failures = [m for m in recorder.measurements if not m.ok]
    if failures:
        lines += ["## 失敗した呼び出し", ""]
        for m in failures[:50]:
            lines.append(f"- `{m.label}` {m.target} → {m.status_code}: {m.error}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_json(data: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
