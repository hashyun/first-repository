"""평점표: 지표별 구간표 → 0~1 점수 → 항목 평균 → 100점 환산."""
from __future__ import annotations

from dataclasses import dataclass, field

from .financials import Valuation, YearRatios
from .macro import MacroSnapshot

# 항목별 배점 (합계 100). 데이터가 없는 항목의 배점은 나머지에 비례 재배분한다.
WEIGHTS = {
    "재무안정성": 25,
    "수익성": 20,
    "성장성": 15,
    "현금흐름": 15,
    "밸류에이션": 10,
    "거시환경": 15,
}

# 구간표: (기준값, 점수) 목록. HIGHER 는 값 >= 기준값, LOWER 는 값 <= 기준값 일 때 해당 점수.
# 어느 구간에도 못 들면 0점. 기준값은 좋은 쪽부터 나열한다.
Table = list[tuple[float, float]]

DEBT_RATIO: Table = [(50, 1), (100, .8), (150, .6), (200, .4), (300, .2)]  # LOWER, %
CURRENT_RATIO: Table = [(200, 1), (150, .8), (120, .6), (100, .4), (80, .2)]  # HIGHER, %
BORROWING_DEP: Table = [(10, 1), (20, .8), (30, .6), (40, .4), (50, .2)]  # LOWER, %
INTEREST_COVER: Table = [(10, 1), (5, .8), (3, .6), (1.5, .4), (1, .2)]  # HIGHER, 배
OP_MARGIN: Table = [(20, 1), (10, .8), (5, .6), (2, .4), (0, .2)]  # HIGHER, %
NET_MARGIN: Table = [(15, 1), (8, .8), (4, .6), (1, .4), (0, .2)]
ROE: Table = [(15, 1), (10, .8), (6, .6), (3, .4), (0, .2)]
ROA: Table = [(8, 1), (5, .8), (3, .6), (1, .4), (0, .2)]
REV_GROWTH: Table = [(20, 1), (10, .8), (5, .6), (0, .4), (-10, .2)]
OP_GROWTH: Table = [(30, 1), (15, .8), (5, .6), (0, .4), (-20, .2)]
CFO_TO_NI: Table = [(1.2, 1), (1.0, .8), (0.8, .6), (0.5, .4), (0, .2)]  # 배
FCF_MARGIN: Table = [(10, 1), (5, .8), (2, .6), (0, .4), (-5, .2)]
PER: Table = [(8, 1), (12, .8), (18, .6), (25, .4), (40, .2)]  # LOWER
PBR: Table = [(0.8, 1), (1.2, .8), (2, .6), (3, .4), (5, .2)]  # LOWER
VOLATILITY: Table = [(20, 1), (30, .8), (40, .6), (50, .4), (70, .2)]  # LOWER, 연환산 %
RATE_CHANGE: Table = [(-0.25, 1), (0.0, .8), (0.25, .5), (0.75, .25)]  # LOWER, %p (6개월)
VIX: Table = [(15, 1), (20, .8), (25, .6), (30, .4), (40, .2)]  # LOWER
YIELD_CURVE: Table = [(0.5, 1), (0.0, .7), (-0.5, .3)]  # HIGHER, %p
FX_CHANGE: Table = [(-3, 1), (3, .8), (7, .5), (12, .25)]  # LOWER, 원화 약세율 % (6개월)


def lookup(value: float | None, table: Table, higher_is_better: bool) -> float | None:
    """구간표 조회. 값이 None 이면 None(=평가 제외)."""
    if value is None:
        return None
    for bound, score in table:
        if (value >= bound) if higher_is_better else (value <= bound):
            return score
    return 0.0


@dataclass
class IndicatorScore:
    label: str
    value: float | None
    unit: str
    score: float | None  # 0~1


@dataclass
class CategoryScore:
    name: str
    weight: float  # 기본 배점
    effective_weight: float = 0.0  # 재배분 후 배점
    ratio: float | None = None  # 0~1, 평가 불가면 None
    points: float | None = None
    indicators: list[IndicatorScore] = field(default_factory=list)


@dataclass
class ScoreCard:
    categories: list[CategoryScore]
    total: float
    grade: str
    notes: list[str] = field(default_factory=list)

    def category(self, name: str) -> CategoryScore | None:
        return next((c for c in self.categories if c.name == name), None)


def grade_for(total: float) -> str:
    for bound, grade in ((90, "A+"), (80, "A"), (70, "B+"), (60, "B"), (50, "C")):
        if total >= bound:
            return grade
    return "D"


def _ind(label, value, unit, table, higher) -> IndicatorScore:
    return IndicatorScore(label, value, unit, lookup(value, table, higher))


def _financial_indicators(latest: YearRatios | None) -> dict[str, list[IndicatorScore]]:
    if latest is None:
        return {n: [] for n in ("재무안정성", "수익성", "성장성", "현금흐름")}
    fcf_margin = latest.fcf_margin
    return {
        "재무안정성": [
            _ind("부채비율", latest.debt_ratio, "%", DEBT_RATIO, False),
            _ind("유동비율", latest.current_ratio, "%", CURRENT_RATIO, True),
            _ind("차입금의존도", latest.borrowing_dependency, "%", BORROWING_DEP, False),
            _ind("이자보상배율", latest.interest_coverage, "배", INTEREST_COVER, True),
        ],
        "수익성": [
            _ind("영업이익률", latest.op_margin, "%", OP_MARGIN, True),
            _ind("순이익률", latest.net_margin, "%", NET_MARGIN, True),
            _ind("ROE", latest.roe, "%", ROE, True),
            _ind("ROA", latest.roa, "%", ROA, True),
        ],
        "성장성": [
            _ind("매출 성장률", latest.revenue_growth, "%", REV_GROWTH, True),
            _ind("영업이익 성장률", latest.op_growth, "%", OP_GROWTH, True),
        ],
        "현금흐름": [
            _ind("영업CF/순이익", latest.cfo_to_ni, "배", CFO_TO_NI, True),
            _ind("FCF/매출", fcf_margin, "%", FCF_MARGIN, True),
        ],
    }


def _valuation_indicators(val: Valuation) -> list[IndicatorScore]:
    per = IndicatorScore("PER", val.per, "배", lookup(val.per, PER, False))
    return [
        per,
        _ind("PBR", val.pbr, "배", PBR, False),
        _ind("1년 변동성(연환산)", val.volatility, "%", VOLATILITY, False),
    ]


def _macro_indicators(macro: MacroSnapshot | None) -> list[IndicatorScore]:
    if macro is None:
        return []
    return [
        _ind("기준금리 6개월 변화", macro.value("kr_base_rate", "change_6m"), "%p", RATE_CHANGE, False),
        _ind("연방기금금리 6개월 변화", macro.value("fed_funds", "change_6m"), "%p", RATE_CHANGE, False),
        _ind("VIX", macro.value("vix"), "pt", VIX, False),
        _ind("미국 장단기 금리차", macro.value("t10y2y"), "%p", YIELD_CURVE, True),
        _ind("원/달러 6개월 변동률", macro.value("usdkrw", "change_6m"), "%", FX_CHANGE, False),
    ]


def score(ratios: list[YearRatios], valuation: Valuation, macro: MacroSnapshot | None) -> ScoreCard:
    """최신 연도 지표 기준 평점. 평가 가능한 항목에 배점을 비례 재배분해 100점 만점으로 환산한다."""
    latest = ratios[-1] if ratios else None
    groups = _financial_indicators(latest)
    groups["밸류에이션"] = _valuation_indicators(valuation)
    groups["거시환경"] = _macro_indicators(macro)

    categories = []
    for name, weight in WEIGHTS.items():
        inds = groups[name]
        scored = [i.score for i in inds if i.score is not None]
        cat = CategoryScore(name, weight, indicators=inds)
        if scored:
            cat.ratio = sum(scored) / len(scored)
        categories.append(cat)

    available = sum(c.weight for c in categories if c.ratio is not None)
    notes = []
    for c in categories:
        if c.ratio is None:
            notes.append(f"{c.name}: 데이터 없음(N/A) — 배점 {c.weight:g}점을 다른 항목에 재배분")
            continue
        c.effective_weight = c.weight * 100 / available
        c.points = c.ratio * c.effective_weight
    total = round(sum(c.points or 0 for c in categories), 1)
    if available == 0:
        notes.append("평가 가능한 데이터가 없어 평점을 산출할 수 없습니다.")
    return ScoreCard(categories, total, grade_for(total) if available else "N/A", notes)
