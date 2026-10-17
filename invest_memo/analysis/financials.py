"""재무비율 계산 (최근 3개 사업연도) 및 밸류에이션."""
from __future__ import annotations

from dataclasses import dataclass, fields

from ..sources.price import PriceInfo


def safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pct(a: float | None, b: float | None) -> float | None:
    r = safe_div(a, b)
    return None if r is None else r * 100


def _growth(cur: float | None, prev: float | None) -> float | None:
    """증가율(%). 기준연도 값이 0 이하이면 의미가 없어 None."""
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100


@dataclass
class YearRatios:
    year: int
    # 원천 금액 (원)
    revenue: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    paid_in_capital: float | None = None
    cfo: float | None = None
    capex: float | None = None
    fcf: float | None = None
    # 비율 (%, 배수는 단위 명시)
    debt_ratio: float | None = None  # 부채/자본 %
    current_ratio: float | None = None  # %
    borrowing_dependency: float | None = None  # 차입금/총자산 %
    interest_coverage: float | None = None  # 배
    op_margin: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    revenue_growth: float | None = None
    op_growth: float | None = None
    cfo_to_ni: float | None = None  # 배 (순이익 > 0 일 때만)
    fcf_margin: float | None = None  # FCF/매출 %

    def has_data(self) -> bool:
        return any(getattr(self, f.name) is not None for f in fields(self) if f.name != "year")


def compute_ratios(years: dict[int, dict[str, float | None]]) -> list[YearRatios]:
    """연도별 원천 계정 → 비율. 오래된 연도부터 최대 3개를 반환한다."""
    out = []
    for year in sorted(years)[-3:]:
        v = years[year]
        prev = years.get(year - 1, {})
        capex = v.get("capex")
        fcf = v["cfo"] - capex if v.get("cfo") is not None and capex is not None else None
        interest = v.get("interest_expense")
        ni = v.get("net_income")
        out.append(
            YearRatios(
                year=year,
                revenue=v.get("revenue"),
                operating_income=v.get("operating_income"),
                net_income=ni,
                total_assets=v.get("total_assets"),
                total_liabilities=v.get("total_liabilities"),
                total_equity=v.get("total_equity"),
                paid_in_capital=v.get("paid_in_capital"),
                cfo=v.get("cfo"),
                capex=capex,
                fcf=fcf,
                debt_ratio=_pct(v.get("total_liabilities"), v.get("total_equity")),
                current_ratio=_pct(v.get("current_assets"), v.get("current_liabilities")),
                borrowing_dependency=_pct(v.get("borrowings"), v.get("total_assets")),
                interest_coverage=safe_div(v.get("operating_income"), abs(interest) if interest else None),
                op_margin=_pct(v.get("operating_income"), v.get("revenue")),
                net_margin=_pct(ni, v.get("revenue")),
                roe=_pct(ni, v.get("total_equity")),
                roa=_pct(ni, v.get("total_assets")),
                revenue_growth=_growth(v.get("revenue"), prev.get("revenue")),
                op_growth=_growth(v.get("operating_income"), prev.get("operating_income")),
                cfo_to_ni=safe_div(v.get("cfo"), ni) if ni is not None and ni > 0 else None,
                fcf_margin=_pct(fcf, v.get("revenue")),
            )
        )
    return out


@dataclass
class Valuation:
    last_close: float | None = None
    per: float | None = None
    pbr: float | None = None
    volatility: float | None = None  # 연환산 %
    drawdown: float | None = None  # 52주 고점 대비 %
    market_cap: float | None = None


def compute_valuation(latest: YearRatios | None, price: PriceInfo | None) -> Valuation:
    """주가 정보가 없으면 빈 Valuation. PER/PBR 은 시가총액이 있을 때만 계산한다."""
    if price is None:
        return Valuation()
    per = pbr = None
    if price.market_cap and latest:
        if latest.net_income and latest.net_income > 0:
            per = price.market_cap / latest.net_income
        if latest.total_equity and latest.total_equity > 0:
            pbr = price.market_cap / latest.total_equity
    return Valuation(
        last_close=price.last_close,
        per=per,
        pbr=pbr,
        volatility=price.volatility_1y,
        drawdown=price.drawdown_from_high,
        market_cap=price.market_cap,
    )
