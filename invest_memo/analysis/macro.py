"""거시 지표 요약."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..sources import Observation


@dataclass
class MacroIndicator:
    key: str
    label: str
    source: str  # ECOS / FRED
    unit: str
    latest: float | None = None
    latest_date: date | None = None
    change_6m: float | None = None  # kind 가 diff 면 %p(단위 차이), pct 면 %
    change_kind: str | None = None  # "diff" | "pct" | None


@dataclass
class MacroSnapshot:
    indicators: dict[str, MacroIndicator] = field(default_factory=dict)

    def get(self, key: str) -> MacroIndicator | None:
        return self.indicators.get(key)

    def value(self, key: str, attr: str = "latest") -> float | None:
        ind = self.indicators.get(key)
        return getattr(ind, attr) if ind else None


def value_at_or_before(obs: list[Observation], target: date, tolerance_days: int = 45) -> Observation | None:
    """target 이하의 가장 가까운 관측치. 너무 오래된 값(tolerance 초과)이면 None."""
    candidates = [o for o in obs if o.date <= target]
    if not candidates:
        return None
    best = max(candidates, key=lambda o: o.date)
    return best if (target - best.date).days <= tolerance_days else None


def yoy_series(obs: list[Observation]) -> list[Observation]:
    """지수 시계열 → 전년동월비(%) 시계열 (마지막 값만 필요하므로 최신 값 기준 계산)."""
    if not obs:
        return []
    latest = obs[-1]
    prior = value_at_or_before(obs, latest.date - timedelta(days=365))
    if prior is None or prior.value == 0:
        return []
    return [Observation(latest.date, (latest.value / prior.value - 1) * 100)]


def make_indicator(
    key: str,
    label: str,
    source: str,
    unit: str,
    obs: list[Observation] | None,
    change_kind: str | None = None,
    yoy: bool = False,
) -> MacroIndicator:
    """관측치 리스트에서 최신값과 6개월 변화를 계산한다. 관측치가 없으면 값이 None 인 지표."""
    ind = MacroIndicator(key, label, source, unit, change_kind=change_kind)
    if not obs:
        return ind
    obs = sorted(obs, key=lambda o: o.date)
    if yoy:
        obs = yoy_series(obs)
        if not obs:
            return ind
    last = obs[-1]
    ind.latest, ind.latest_date = last.value, last.date
    if change_kind:
        past = value_at_or_before(obs, last.date - timedelta(days=182))
        if past:
            ind.change_6m = (
                last.value - past.value if change_kind == "diff" else (last.value / past.value - 1) * 100
            )
    return ind


def build_snapshot(ecos: dict[str, list[Observation]], fred: dict[str, list[Observation]]) -> MacroSnapshot:
    """원시 시계열 → MacroSnapshot. 키가 없거나 비어 있으면 해당 지표는 N/A."""
    spec = [
        ("kr_base_rate", "한국은행 기준금리", "ECOS", "%", ecos, "diff", False),
        ("kr_3y", "국고채 3년", "ECOS", "%", ecos, "diff", False),
        ("usdkrw", "원/달러 환율", "ECOS", "원", ecos, "pct", False),
        ("kr_cpi", "소비자물가 상승률(전년동월비)", "ECOS", "%", ecos, None, True),
        ("fed_funds", "미국 연방기금금리", "FRED", "%", fred, "diff", False),
        ("us10y", "미국 국채 10년", "FRED", "%", fred, "diff", False),
        ("vix", "VIX", "FRED", "pt", fred, None, False),
        ("t10y2y", "미국 장단기 금리차(10Y-2Y)", "FRED", "%p", fred, None, False),
        ("us_cpi", "미국 CPI 상승률(전년동월비)", "FRED", "%", fred, None, True),
    ]
    snap = MacroSnapshot()
    for key, label, src, unit, store, kind, yoy in spec:
        snap.indicators[key] = make_indicator(key, label, src, unit, store.get(key), kind, yoy)
    return snap


def regime_label(macro_ratio: float | None) -> str:
    """거시 점수 비율(0~1) → 국면 판단."""
    if macro_ratio is None:
        return "판단불가 (데이터 부족)"
    if macro_ratio >= 0.7:
        return "우호적"
    if macro_ratio >= 0.45:
        return "중립"
    return "경계"
