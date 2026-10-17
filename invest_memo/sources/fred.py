"""FRED 클라이언트 (https://fred.stlouisfed.org)."""
from __future__ import annotations

from datetime import date

from ..cache import FileCache, cached
from . import Observation, SourceError, request_with_retry

URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "fed_funds": ("DFF", "연방기금금리"),
    "us10y": ("DGS10", "미국 국채 10년"),
    "vix": ("VIXCLS", "VIX"),
    "t10y2y": ("T10Y2Y", "장단기 금리차(10Y-2Y)"),
    "us_cpi": ("CPIAUCSL", "미국 CPI"),
}


class FredClient:
    def __init__(self, api_key: str, cache: FileCache | None = None):
        self.api_key = api_key
        self.cache = cache

    def observations(self, series_id: str, start: date, end: date | None = None) -> list[Observation]:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
        }
        if end:
            params["observation_end"] = end.isoformat()

        def fetch():
            body = request_with_retry(URL, params).json()
            if "observations" not in body:
                raise SourceError(f"FRED {series_id}: {body.get('error_message', '응답 형식 오류')}")
            return [{"date": o["date"], "value": o["value"]} for o in body["observations"]]

        cache_key = f"fred:{series_id}:{params['observation_start']}:{params.get('observation_end', '')}"
        rows = cached(self.cache, cache_key, fetch)
        out = []
        for r in rows:
            if r["value"] in (".", "", None):  # FRED 결측값
                continue
            try:
                out.append(Observation(date.fromisoformat(r["date"]), float(r["value"])))
            except ValueError:
                continue
        return out

    def series(self, key: str, start: date, end: date | None = None) -> list[Observation]:
        return self.observations(SERIES[key][0], start, end)
