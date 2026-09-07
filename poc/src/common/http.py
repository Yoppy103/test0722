"""HTTP 層: レート制限・リトライ・計測・トレースログを1か所に集約。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .timing import Measurement, Recorder


class RateLimiter:
    """単純なトークン間隔方式。Bカートの 300req/300sec ロック対策。

    「超過すると300秒ロック」という仕様は PoC を丸ごと止めうるので、
    速度より安全側に倒す。実測後に max_per_sec を上げて再計測する運用。
    """

    def __init__(self, max_per_sec: float) -> None:
        self.min_interval = 1.0 / max_per_sec if max_per_sec > 0 else 0.0
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """必要なら待機し、待った秒数を返す（計測から除外するため）。"""
        if self.min_interval <= 0:
            return 0.0
        with self._lock:
            now = time.perf_counter()
            wait = self._last + self.min_interval - now
            if wait > 0:
                time.sleep(wait)
            else:
                wait = 0.0
            self._last = time.perf_counter()
            return wait


@dataclass
class Response:
    status_code: int
    body: Any
    headers: dict[str, str]
    elapsed_ms: float

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class ApiClient:
    """ベンダ共通の HTTP クライアント。

    - 429/5xx は指数バックオフでリトライ（リトライ待ちは計測から除外）
    - 全リクエストを JSONL でトレース出力（検証の証跡としてそのまま納品できる）
    """

    def __init__(
        self,
        base_url: str,
        *,
        vendor: str,
        recorder: Recorder,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        trace_path: Path | None = None,
        verbose: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.vendor = vendor
        self.recorder = recorder
        self.rate_limiter = rate_limiter or RateLimiter(0)
        self.timeout = timeout
        self.max_retries = max_retries
        self.trace_path = trace_path
        self.verbose = verbose
        self.session = requests.Session()
        self._headers: dict[str, str] = {"Accept": "application/json"}

    def set_bearer(self, token: str) -> None:
        self._headers["Authorization"] = f"Bearer {token}"

    def set_header(self, key: str, value: str) -> None:
        self._headers[key] = value

    def request(
        self,
        method: str,
        path: str,
        *,
        label: str = "request",
        target: str = "",
        params: dict | None = None,
        json_body: dict | list | None = None,
        measure: bool = True,
    ) -> Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        throttle_wait = self.rate_limiter.acquire() * 1000.0
        retry_wait_ms = 0.0
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                raw = self.session.request(
                    method,
                    url,
                    headers=self._headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                resp = Response(
                    status_code=raw.status_code,
                    body=_parse(raw),
                    headers=dict(raw.headers),
                    elapsed_ms=elapsed_ms,
                )
                self._trace(method, url, json_body, resp, attempt)

                # 429 / 5xx はリトライ対象。それ以外は成否問わず呼び出し元に返す。
                if raw.status_code == 429 or 500 <= raw.status_code < 600:
                    if attempt < self.max_retries:
                        retry_wait_ms += self._backoff(attempt, raw)
                        continue

                if measure:
                    self.recorder.add(
                        Measurement(
                            label=label,
                            target=target or url,
                            elapsed_ms=elapsed_ms,
                            status_code=raw.status_code,
                            ok=resp.ok,
                            error=None if resp.ok else _short(resp.body),
                            throttle_wait_ms=throttle_wait + retry_wait_ms,
                            extra={"method": method, "attempts": attempt + 1},
                        )
                    )
                return resp

            except requests.RequestException as exc:
                last_exc = exc
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                self._trace(method, url, json_body, None, attempt, error=str(exc))
                if attempt < self.max_retries:
                    retry_wait_ms += self._backoff(attempt, None)
                    continue
                if measure:
                    self.recorder.add(
                        Measurement(
                            label=label,
                            target=target or url,
                            elapsed_ms=elapsed_ms,
                            status_code=None,
                            ok=False,
                            error=f"{type(exc).__name__}: {exc}",
                            throttle_wait_ms=throttle_wait + retry_wait_ms,
                            extra={"method": method, "attempts": attempt + 1},
                        )
                    )
                raise

        raise RuntimeError(f"unreachable: {last_exc}")

    def _backoff(self, attempt: int, raw: requests.Response | None) -> float:
        """Retry-After を尊重しつつ指数バックオフ。待った ms を返す。"""
        wait = 2.0 ** attempt
        if raw is not None:
            header = raw.headers.get("Retry-After")
            if header:
                try:
                    wait = max(wait, float(header))
                except ValueError:
                    pass
        if self.verbose:
            print(f"  [retry] attempt={attempt + 1} wait={wait:.1f}s")
        time.sleep(wait)
        return wait * 1000.0

    def _trace(
        self,
        method: str,
        url: str,
        body: Any,
        resp: Response | None,
        attempt: int,
        error: str | None = None,
    ) -> None:
        if self.verbose:
            code = resp.status_code if resp else "ERR"
            print(f"  [{self.vendor}] {method} {url} -> {code}")
        if not self.trace_path:
            return
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "vendor": self.vendor,
            "method": method,
            "url": url,
            "attempt": attempt + 1,
            "request_body": _redact(body),
            "status": resp.status_code if resp else None,
            "response_body": _short(resp.body) if resp else None,
            "error": error,
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


SECRET_KEYS = {"client_secret", "password", "access_token", "refresh_token", "code"}


def _redact(body: Any) -> Any:
    """トレースを納品物に含めるため、資格情報は必ず伏せる。"""
    if isinstance(body, dict):
        return {k: ("***" if k in SECRET_KEYS else _redact(v)) for k, v in body.items()}
    if isinstance(body, list):
        return [_redact(v) for v in body]
    return body


def _parse(raw: requests.Response) -> Any:
    try:
        return raw.json()
    except ValueError:
        return raw.text


def _short(body: Any, limit: int = 400) -> str:
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"
