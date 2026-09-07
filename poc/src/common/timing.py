"""所要時間の計測と統計。検証項目2「更新1件あたりの所要時間」の中核。"""
from __future__ import annotations

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Iterator


@dataclass
class Measurement:
    """API 呼び出し1回分の計測結果。"""

    label: str
    target: str          # 例: "smaregi:product=1001,customer_group=2"
    elapsed_ms: float
    status_code: int | None = None
    ok: bool = True
    error: str | None = None
    # 待ち時間（レート制限のスリープ）は純粋なAPI応答時間と分けて記録する。
    # これを混ぜると「1件あたりの所要時間」が制限待ちで水増しされてしまう。
    throttle_wait_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("extra")
        row.update(self.extra)
        return row


class Recorder:
    """計測結果を溜めて統計を出す。"""

    def __init__(self) -> None:
        self.measurements: list[Measurement] = []

    def add(self, m: Measurement) -> None:
        self.measurements.append(m)

    @contextmanager
    def measure(self, label: str, target: str) -> Iterator[Measurement]:
        m = Measurement(label=label, target=target, elapsed_ms=0.0)
        start = time.perf_counter()
        try:
            yield m
        except Exception as exc:  # 失敗も所要時間の母集団として残す
            m.ok = False
            m.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            m.elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.add(m)

    def summary(self, label: str | None = None) -> dict[str, Any]:
        rows = [m for m in self.measurements if label is None or m.label == label]
        ok = [m.elapsed_ms for m in rows if m.ok]
        if not ok:
            return {"label": label or "all", "count": len(rows), "ok_count": 0}
        ok.sort()
        return {
            "label": label or "all",
            "count": len(rows),
            "ok_count": len(ok),
            "ng_count": len(rows) - len(ok),
            "min_ms": round(min(ok), 1),
            "avg_ms": round(statistics.fmean(ok), 1),
            "p50_ms": round(_percentile(ok, 50), 1),
            "p95_ms": round(_percentile(ok, 95), 1),
            "max_ms": round(max(ok), 1),
            "total_throttle_wait_ms": round(
                sum(m.throttle_wait_ms for m in rows), 1
            ),
        }

    def labels(self) -> list[str]:
        seen: list[str] = []
        for m in self.measurements:
            if m.label not in seen:
                seen.append(m.label)
        return seen


def _percentile(sorted_values: list[float], pct: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    # 線形補間（小サンプルでも極端な値にならないように）
    k = (len(sorted_values) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)
