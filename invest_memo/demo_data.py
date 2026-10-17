"""--demo 용 번들 데이터. 모든 수치는 가상의 값이며 실제 기업과 무관하다."""
from __future__ import annotations

from datetime import date, timedelta

from .report.builder import DataBundle
from .sources import Observation
from .sources.dart import Disclosure, FinancialStatements, Shareholder
from .sources.price import PriceInfo

EOK = 100_000_000  # 억원


def _monthly(today: date, values: list[float]) -> list[Observation]:
    """오늘 기준 지난달부터 거슬러 올라가며 월별 관측치를 만든다 (values 는 과거 → 최근 순)."""
    out = []
    y, m = today.year, today.month
    for v in reversed(values):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(Observation(date(y, m, 1), v))
    return sorted(out, key=lambda o: o.date)


def _daily(today: date, values: list[float], step_days: int = 30) -> list[Observation]:
    n = len(values)
    return [Observation(today - timedelta(days=step_days * (n - 1 - i)), v) for i, v in enumerate(values)]


def load_demo(today: date | None = None) -> DataBundle:
    today = today or date.today()
    year = today.year - 1

    def acct(rev, op, ni, assets, liab, equity, ca, cl, borrow, interest, cfo, capex, capital):
        return {
            "revenue": rev * EOK, "operating_income": op * EOK, "net_income": ni * EOK,
            "total_assets": assets * EOK, "total_liabilities": liab * EOK, "total_equity": equity * EOK,
            "current_assets": ca * EOK, "current_liabilities": cl * EOK, "borrowings": borrow * EOK,
            "interest_expense": interest * EOK, "cfo": cfo * EOK, "capex": capex * EOK,
            "paid_in_capital": capital * EOK,
        }

    financial = FinancialStatements(
        "CFS",
        {
            year - 2: acct(21_000, 1_900, 1_500, 30_000, 12_500, 17_500, 14_000, 7_500, 3_800, 150, 2_600, 1_500, 600),
            year - 1: acct(23_400, 2_500, 1_950, 32_500, 13_300, 19_200, 15_500, 8_000, 3_900, 160, 3_100, 1_700, 600),
            year: acct(26_200, 3_300, 2_700, 35_800, 14_200, 21_600, 17_400, 8_400, 3_700, 150, 3_900, 2_000, 600),
        },
    )
    d = lambda days_ago, title: Disclosure(  # noqa: E731
        (today - timedelta(days=days_ago)).isoformat(), title, "데모전자", f"2026{days_ago:04d}000001"
    )
    return DataBundle(
        stock_code="000000",
        company_name="데모전자(가상)",
        company_info={
            "ceo_nm": "홍길동", "induty_code": "26110", "est_dt": "19900315", "acc_mt": "12",
            "adres": "서울특별시 (가상 주소)", "hm_url": "www.example.com",
        },
        shareholders=[
            Shareholder("가상홀딩스", "최대주주", 41_000_000, 20.5),
            Shareholder("홍길동", "특수관계인", 6_000_000, 3.0),
            Shareholder("가상연금공단", "5% 이상 주주", 11_000_000, 5.5),
        ],
        financial=financial,
        disclosures=[
            d(5, "분기보고서"),
            d(18, "주요사항보고서(자기주식취득결정)"),
            d(40, "영업(잠정)실적(공정공시)"),
            d(75, "임원ㆍ주요주주특정증권등소유상황보고서"),
        ],
        ecos={
            "kr_base_rate": _monthly(today, [3.50, 3.50, 3.25, 3.25, 3.00, 3.00, 2.75, 2.75]),
            "usdkrw": _monthly(today, [1_380, 1_375, 1_360, 1_355, 1_350, 1_345, 1_340, 1_350]),
            "kr_cpi": _monthly(today, [112.0 + 0.2 * i for i in range(16)]),
            "kr_3y": _daily(today, [2.7, 2.65, 2.6]),
        },
        fred={
            "fed_funds": _daily(today, [4.5, 4.4, 4.3, 4.25, 4.0, 3.9, 3.8, 3.75], step_days=30),
            "us10y": _daily(today, [4.2, 4.1, 4.0]),
            "vix": _daily(today, [18.0, 16.5, 15.2]),
            "t10y2y": _daily(today, [0.35, 0.4, 0.45]),
            "us_cpi": _monthly(today, [300 + 0.7 * i for i in range(16)]),
        },
        price=PriceInfo(last_close=72_000, high_52w=80_000, low_52w=55_000, volatility_1y=28.0, market_cap=215_000 * EOK / 10),
        notes=["데모 모드: 번들된 가상 데이터를 사용했으며 외부 API 를 호출하지 않았습니다."],
        is_demo=True,
    )
