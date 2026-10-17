"""한국은행 ECOS 클라이언트 (https://ecos.bok.or.kr/api)."""
from __future__ import annotations

from datetime import date

from ..cache import FileCache, cached
from . import Observation, SourceError, request_with_retry

BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

# 키 → (통계표코드, 주기, 항목코드, 설명)
SERIES = {
    "kr_base_rate": ("722Y001", "M", "0101000", "한국은행 기준금리"),
    "usdkrw": ("731Y001", "M", "0000001", "원/달러 환율"),
    "kr_cpi": ("901Y009", "M", "0", "소비자물가지수(총지수)"),
    "kr_3y": ("817Y002", "D", "010200000", "국고채(3년)"),
}


def parse_time(text: str) -> date:
    """ECOS TIME 문자열(YYYY / YYYYMM / YYYYMMDD) → date."""
    text = text.strip()
    if len(text) == 8:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    if len(text) == 6:
        return date(int(text[:4]), int(text[4:6]), 1)
    if len(text) == 4:
        return date(int(text), 1, 1)
    raise ValueError(f"알 수 없는 TIME 형식: {text}")


def format_period(cycle: str, d: date) -> str:
    return {"D": d.strftime("%Y%m%d"), "M": d.strftime("%Y%m"), "A": d.strftime("%Y")}[cycle]


class EcosClient:
    def __init__(self, api_key: str, cache: FileCache | None = None):
        self.api_key = api_key
        self.cache = cache

    def statistic(self, stat: str, cycle: str, start: date, end: date, item: str) -> list[Observation]:
        """.../StatisticSearch/{KEY}/json/kr/1/100/{STAT}/{CYCLE}/{START}/{END}/{ITEM}"""
        tail = f"json/kr/1/100/{stat}/{cycle}/{format_period(cycle, start)}/{format_period(cycle, end)}/{item}"

        def fetch():
            body = request_with_retry(f"{BASE}/{self.api_key}/{tail}").json()
            if "StatisticSearch" in body:
                return [
                    {"time": r["TIME"], "value": r["DATA_VALUE"]} for r in body["StatisticSearch"].get("row", [])
                ]
            result = body.get("RESULT", {})
            if result.get("CODE") == "INFO-200":  # 해당 데이터 없음
                return []
            raise SourceError(f"ECOS {stat}: [{result.get('CODE')}] {result.get('MESSAGE')}")

        rows = cached(self.cache, f"ecos:{tail}", fetch)
        out = []
        for r in rows:
            try:
                out.append(Observation(parse_time(r["time"]), float(str(r["value"]).replace(",", ""))))
            except (ValueError, KeyError):
                continue  # 결측/이상값은 건너뛴다
        return sorted(out, key=lambda o: o.date)

    def series(self, key: str, start: date, end: date) -> list[Observation]:
        stat, cycle, item, _ = SERIES[key]
        return self.statistic(stat, cycle, start, end, item)
