"""외부 데이터 소스 공통 유틸."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import requests


class SourceError(RuntimeError):
    """외부 API 호출/응답 오류."""


@dataclass(frozen=True)
class Observation:
    date: date
    value: float


def request_with_retry(
    url: str, params: dict | None = None, timeout: float = 15, retries: int = 2
) -> requests.Response:
    """GET + 타임아웃 + 단순 재시도(지수 백오프)."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    # URL 에는 API 키가 포함될 수 있으므로 메시지에 넣지 않는다.
    raise SourceError(f"요청 실패: {type(last).__name__}")
