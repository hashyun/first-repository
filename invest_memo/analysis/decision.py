"""승인 판정, 투자한도, 승인조건(약정), 녹아웃/경고."""
from __future__ import annotations

from dataclasses import dataclass, field


from ..sources.dart import Disclosure
from .financials import Valuation, YearRatios
from .macro import MacroSnapshot
from .scoring import ScoreCard

APPROVE, CONDITIONAL, HOLD, REJECT = "승인", "조건부승인", "보류", "거절"

# 등급 → (기본 판정, 투자한도 % of 포트폴리오)
GRADE_POLICY = {
    "A+": (APPROVE, 10.0),
    "A": (APPROVE, 10.0),
    "B+": (APPROVE, 7.0),
    "B": (CONDITIONAL, 5.0),
    "C": (HOLD, 0.0),
    "D": (REJECT, 0.0),
}
GRADE_ORDER = ["D", "C", "B", "B+", "A", "A+"]

# 최근 90일 공시 제목에 이 키워드가 있으면 녹아웃(거절). 주의 키워드는 경고만 한다.
REJECT_KEYWORDS = ("횡령", "배임", "거래정지", "상장폐지", "의견거절", "부적정", "한정의견", "감사의견 비적정")
WARN_KEYWORDS = ("관리종목", "투자주의환기", "불성실공시", "회생절차", "영업정지", "유상증자", "감자")


@dataclass
class Flag:
    level: str  # "reject" | "downgrade" | "warning"
    title: str
    detail: str


@dataclass
class Decision:
    verdict: str
    grade: str
    score: float
    limit_pct: float  # 포트폴리오 대비 %
    requested_amount: float
    approved_amount: float
    reduced: bool
    flags: list[Flag] = field(default_factory=list)
    covenants: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    stop_loss_pct: float | None = None


def collect_flags(
    ratios: list[YearRatios],
    disclosures: list[Disclosure],
    valuation: Valuation,
    macro: MacroSnapshot | None,
    scorecard: ScoreCard,
) -> list[Flag]:
    flags: list[Flag] = []
    latest = ratios[-1] if ratios else None
    prev = ratios[-2] if len(ratios) >= 2 else None

    # --- 녹아웃 ---
    if latest and latest.total_equity is not None:
        if latest.total_equity <= 0:
            flags.append(Flag("reject", "완전자본잠식", "자기자본이 0 이하입니다."))
        elif latest.paid_in_capital and latest.total_equity < latest.paid_in_capital:
            flags.append(Flag("reject", "부분자본잠식", "자기자본이 자본금보다 작습니다."))
    if latest and prev and None not in (latest.operating_income, prev.operating_income):
        if latest.operating_income < 0 and prev.operating_income < 0:
            flags.append(Flag("downgrade", "2년 연속 영업적자", f"{prev.year}·{latest.year}년 영업손실"))
    if latest and prev and None not in (latest.interest_coverage, prev.interest_coverage):
        if latest.interest_coverage < 1 and prev.interest_coverage < 1:
            flags.append(Flag("downgrade", "이자보상배율 2년 연속 1 미만", "영업이익으로 이자 비용을 감당하지 못함"))
    for d in disclosures:
        hit = next((k for k in REJECT_KEYWORDS if k in d.title), None)
        if hit:
            flags.append(Flag("reject", f"공시 키워드 '{hit}'", f"{d.date} {d.title}"))
            continue
        hit = next((k for k in WARN_KEYWORDS if k in d.title), None)
        if hit:
            flags.append(Flag("warning", f"공시 주의 '{hit}'", f"{d.date} {d.title}"))

    # --- 경고 ---
    if latest:
        if latest.debt_ratio is not None and latest.debt_ratio > 200:
            flags.append(Flag("warning", "높은 부채비율", f"{latest.debt_ratio:.0f}% (기준 200%)"))
        if latest.interest_coverage is not None and 1 <= latest.interest_coverage < 1.5:
            flags.append(Flag("warning", "낮은 이자보상배율", f"{latest.interest_coverage:.2f}배"))
        if latest.net_income is not None and latest.net_income < 0:
            flags.append(Flag("warning", "당기순손실", f"{latest.year}년 순손실 발생"))
        if latest.cfo is not None and latest.cfo < 0:
            flags.append(Flag("warning", "영업현금흐름 마이너스", f"{latest.year}년"))
    if valuation.volatility is not None and valuation.volatility > 50:
        flags.append(Flag("warning", "높은 주가 변동성", f"연환산 {valuation.volatility:.0f}%"))
    if macro:
        vix = macro.value("vix")
        if vix is not None and vix > 30:
            flags.append(Flag("warning", "시장 변동성 확대", f"VIX {vix:.1f}"))
        curve = macro.value("t10y2y")
        if curve is not None and curve < 0:
            flags.append(Flag("warning", "미국 장단기 금리 역전", f"10Y-2Y {curve:+.2f}%p"))
    for note in scorecard.notes:
        flags.append(Flag("warning", "데이터 공백", note))
    return flags


def _cap_grade(grade: str, cap: str) -> str:
    if grade not in GRADE_ORDER:
        return cap
    return grade if GRADE_ORDER.index(grade) <= GRADE_ORDER.index(cap) else cap


def build_covenants(verdict: str, latest: YearRatios | None, valuation: Valuation) -> tuple[list[str], float | None]:
    """승인조건. 반환: (조건 목록, 손절선 %)."""
    if verdict in (REJECT,):
        return ["해당 없음 (거절). 재신청은 녹아웃 사유 해소 및 다음 사업연도 재무제표 확인 후 가능."], None
    if verdict == HOLD:
        return ["보류: 다음 분기 실적 발표 후 재심사. 그 전까지 신규 매수 없음."], None
    vol = valuation.volatility
    stop = 10.0 if vol is None else min(15.0, max(8.0, round(vol * 0.4)))
    covenants = [f"손절선: 진입가 대비 -{stop:g}% 도달 시 전량 재검토/청산 ({'변동성 기반' if vol is not None else '변동성 데이터 없음, 기본값'})"]
    debt_limit = 200.0
    if latest and latest.debt_ratio is not None:
        debt_limit = max(100.0, round(latest.debt_ratio * 1.25 / 10) * 10)
    covenants.append("재심사 트리거: 분기 실적 발표 시")
    covenants.append(f"재심사 트리거: 부채비율 {debt_limit:g}% 초과 시")
    covenants.append("재심사 트리거: 한국은행 기준금리 변경 시")
    if verdict == CONDITIONAL:
        covenants.append("분할매수: 승인금액을 3회(40% / 30% / 30%)로 나누어 진입, 회차 간 최소 2주 간격")
    return covenants, stop


def decide(
    scorecard: ScoreCard,
    flags: list[Flag],
    ratios: list[YearRatios],
    valuation: Valuation,
    requested_amount: float,
    portfolio_value: float,
) -> Decision:
    rationale: list[str] = []
    grade = scorecard.grade
    if grade == "N/A":
        verdict, limit_pct = HOLD, 0.0
        rationale.append("평가 가능한 데이터가 없어 판정을 보류합니다.")
    else:
        verdict, limit_pct = GRADE_POLICY[grade]
        rationale.append(f"평점 {scorecard.total:.1f}점 → 내부등급 {grade} → 기본 판정 {verdict}, 한도 {limit_pct:g}%")

    rejects = [f for f in flags if f.level == "reject"]
    downgrades = [f for f in flags if f.level == "downgrade"]
    if rejects:
        verdict, grade, limit_pct = REJECT, "D", 0.0
        rationale.append("녹아웃(거절) 사유: " + ", ".join(f.title for f in rejects))
    elif downgrades and verdict in (APPROVE, CONDITIONAL):
        verdict, grade, limit_pct = HOLD, _cap_grade(grade, "C"), 0.0
        rationale.append("녹아웃(등급 하향) 사유로 보류 처리: " + ", ".join(f.title for f in downgrades))
    elif downgrades:
        rationale.append("등급 하향 사유 존재: " + ", ".join(f.title for f in downgrades))

    limit_amount = portfolio_value * limit_pct / 100
    approved = min(requested_amount, limit_amount)
    reduced = limit_pct > 0 and requested_amount > limit_amount
    if reduced:
        rationale.append(f"신청금액이 한도({limit_amount:,.0f}원)를 초과하여 한도 내로 감액 승인")
    covenants, stop = build_covenants(verdict, ratios[-1] if ratios else None, valuation)
    return Decision(
        verdict=verdict,
        grade=grade,
        score=scorecard.total,
        limit_pct=limit_pct,
        requested_amount=requested_amount,
        approved_amount=approved,
        reduced=reduced,
        flags=flags,
        covenants=covenants,
        rationale=rationale,
        stop_loss_pct=stop,
    )


