"""수집 데이터 → 분석 → MemoData 조립."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..analysis import decision as dec
from ..analysis.financials import Valuation, YearRatios, compute_ratios, compute_valuation
from ..analysis.macro import MacroSnapshot, build_snapshot, regime_label
from ..analysis.scoring import ScoreCard, score
from ..cache import FileCache
from ..config import Settings
from ..llm.base import LLMProvider, generate_with_fallback
from ..sources import Observation
from ..sources.dart import DartClient, Disclosure, FinancialStatements, Shareholder
from ..sources.ecos import EcosClient
from ..sources.fred import FredClient
from ..sources.price import PriceInfo, fetch_price_info


# --- 포맷터 ------------------------------------------------------------------
def fmt_num(v: float | None, nd: int = 1, suffix: str = "") -> str:
    return "N/A" if v is None else f"{v:,.{nd}f}{suffix}"


def fmt_eok(v: float | None) -> str:
    """원 → 억원."""
    return "N/A" if v is None else f"{v / 1e8:,.0f}"


def fmt_won(v: float | None) -> str:
    return "N/A" if v is None else f"{v:,.0f}원"


# --- 데이터 묶음 ---------------------------------------------------------------
@dataclass
class DataBundle:
    stock_code: str
    company_name: str
    company_info: dict = field(default_factory=dict)  # DART company.json
    shareholders: list[Shareholder] | None = None
    financial: FinancialStatements | None = None
    disclosures: list[Disclosure] | None = None  # None = 조회 불가
    ecos: dict[str, list[Observation]] = field(default_factory=dict)
    fred: dict[str, list[Observation]] = field(default_factory=dict)
    price: PriceInfo | None = None
    notes: list[str] = field(default_factory=list)  # 데이터 수집 비고
    is_demo: bool = False


def collect_live(
    settings: Settings, stock_code: str, year: int, today: date | None = None, cache: FileCache | None = None
) -> DataBundle:
    """실제 API 로 데이터를 수집한다. 소스별 실패는 notes 에 남기고 계속 진행한다."""
    today = today or date.today()
    cache = cache or FileCache(settings.cache_dir, settings.cache_ttl_seconds)
    b = DataBundle(stock_code=stock_code, company_name=stock_code)

    if settings.dart_api_key:
        dart = DartClient(settings.dart_api_key, cache)
        try:
            corp = dart.find_corp(stock_code)
            b.company_name = corp.corp_name
            steps = {
                "company_info": lambda: dart.company(corp.corp_code),
                "financial": lambda: dart.financials(corp.corp_code, year),
                "disclosures": lambda: dart.disclosures(corp.corp_code, 90, today),
                "shareholders": lambda: dart.major_shareholders(corp.corp_code, year),
            }
            for attr, call in steps.items():
                try:
                    setattr(b, attr, call())
                except Exception as exc:
                    b.notes.append(f"OpenDART {attr} 조회 실패: {exc}")
        except Exception as exc:
            b.notes.append(f"OpenDART 기업 조회 실패: {exc}")
    else:
        b.notes.append("DART_API_KEY 없음: 기업개요·재무·공시 항목은 N/A")

    if settings.ecos_api_key:
        ecos = EcosClient(settings.ecos_api_key, cache)
        windows = {"kr_base_rate": 400, "usdkrw": 400, "kr_cpi": 460, "kr_3y": 30}
        for key, days in windows.items():
            try:
                b.ecos[key] = ecos.series(key, today - timedelta(days=days), today)
            except Exception as exc:
                b.notes.append(f"ECOS {key} 조회 실패: {exc}")
    else:
        b.notes.append("ECOS_API_KEY 없음: 국내 거시 지표는 N/A")

    if settings.fred_api_key:
        fred = FredClient(settings.fred_api_key, cache)
        windows = {"fed_funds": 260, "us10y": 30, "vix": 30, "t10y2y": 30, "us_cpi": 460}
        for key, days in windows.items():
            try:
                b.fred[key] = fred.series(key, today - timedelta(days=days), today)
            except Exception as exc:
                b.notes.append(f"FRED {key} 조회 실패: {exc}")
    else:
        b.notes.append("FRED_API_KEY 없음: 미국/글로벌 거시 지표는 N/A")

    b.price = fetch_price_info(stock_code, today)
    if b.price is None:
        b.notes.append("주가 데이터 없음(FinanceDataReader 미설치 또는 조회 실패): 밸류에이션 항목은 N/A")
    return b


# --- MemoData ----------------------------------------------------------------
@dataclass
class MemoData:
    stock_code: str
    company_name: str
    request_date: date
    requested_amount: float
    portfolio_value: float
    reviewer: str
    company_rows: list[tuple[str, str]]
    shareholders: list[Shareholder] | None
    fs_div_label: str
    fin_years: list[int]
    fin_amount_rows: list[tuple[str, list[str]]]
    fin_ratio_rows: list[tuple[str, list[str]]]
    fin_comments: list[str]
    valuation_rows: list[tuple[str, str]]
    macro_rows: list[tuple[str, str, str, str, str]]
    macro_regime: str
    disclosures: list[Disclosure] | None
    scorecard: ScoreCard
    decision: dec.Decision
    opinion: str
    opinion_source: str
    notes: list[str]
    is_demo: bool = False
    model_name: str = ""


def _company_rows(b: DataBundle) -> list[tuple[str, str]]:
    c = b.company_info or {}
    est = c.get("est_dt", "")
    est = f"{est[:4]}-{est[4:6]}-{est[6:8]}" if len(est) == 8 else (est or "N/A")
    return [
        ("회사명", b.company_name or "N/A"),
        ("종목코드", b.stock_code),
        ("대표이사", c.get("ceo_nm") or "N/A"),
        ("업종코드", c.get("induty_code") or "N/A"),
        ("설립일", est),
        ("결산월", f"{c['acc_mt']}월" if c.get("acc_mt") else "N/A"),
        ("소재지", c.get("adres") or "N/A"),
        ("홈페이지", c.get("hm_url") or "N/A"),
    ]


def _amount_rows(r: list[YearRatios]) -> list[tuple[str, list[str]]]:
    spec = [
        ("매출액", "revenue"),
        ("영업이익", "operating_income"),
        ("당기순이익", "net_income"),
        ("자산총계", "total_assets"),
        ("부채총계", "total_liabilities"),
        ("자본총계", "total_equity"),
        ("영업활동현금흐름", "cfo"),
        ("FCF(영업CF-CAPEX)", "fcf"),
    ]
    return [(label, [fmt_eok(getattr(y, attr)) for y in r]) for label, attr in spec]


def _ratio_rows(r: list[YearRatios]) -> list[tuple[str, list[str]]]:
    spec = [
        ("부채비율(%)", "debt_ratio", 1),
        ("유동비율(%)", "current_ratio", 1),
        ("차입금의존도(%)", "borrowing_dependency", 1),
        ("이자보상배율(배)", "interest_coverage", 2),
        ("영업이익률(%)", "op_margin", 1),
        ("순이익률(%)", "net_margin", 1),
        ("ROE(%)", "roe", 1),
        ("ROA(%)", "roa", 1),
        ("매출 성장률(%)", "revenue_growth", 1),
        ("영업이익 성장률(%)", "op_growth", 1),
        ("영업CF/순이익(배)", "cfo_to_ni", 2),
        ("FCF/매출(%)", "fcf_margin", 1),
    ]
    return [(label, [fmt_num(getattr(y, attr), nd) for y in r]) for label, attr, nd in spec]


def _fin_comments(r: list[YearRatios]) -> list[str]:
    if not r:
        return ["재무제표 데이터를 확보하지 못했습니다 (N/A)."]
    cur = r[-1]
    out = []
    if cur.revenue_growth is not None:
        out.append(f"{cur.year}년 매출은 전년 대비 {cur.revenue_growth:+.1f}% 변동했습니다.")
    if len(r) >= 2:
        prev = r[-2]
        if cur.op_margin is not None and prev.op_margin is not None:
            out.append(f"영업이익률은 {prev.op_margin:.1f}%에서 {cur.op_margin:.1f}%로 {cur.op_margin - prev.op_margin:+.1f}%p 변화했습니다.")
        if cur.debt_ratio is not None and prev.debt_ratio is not None:
            out.append(f"부채비율은 {prev.debt_ratio:.0f}%에서 {cur.debt_ratio:.0f}%로 {cur.debt_ratio - prev.debt_ratio:+.0f}%p 변화했습니다.")
    if cur.fcf is not None:
        out.append(f"{cur.year}년 FCF는 {fmt_eok(cur.fcf)}억원({'흑자' if cur.fcf >= 0 else '적자'})입니다.")
    return out or ["비교 가능한 연도 데이터가 부족합니다 (N/A)."]


def _valuation_rows(v: Valuation) -> list[tuple[str, str]]:
    return [
        ("현재가(최근 종가)", fmt_won(v.last_close)),
        ("시가총액", fmt_won(v.market_cap)),
        ("PER(배)", fmt_num(v.per, 1)),
        ("PBR(배)", fmt_num(v.pbr, 2)),
        ("1년 변동성(연환산 %)", fmt_num(v.volatility, 1)),
        ("52주 고점 대비 낙폭(%)", fmt_num(v.drawdown, 1)),
    ]


def _macro_rows(snap: MacroSnapshot) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for ind in snap.indicators.values():
        if ind.latest is None:
            rows.append((ind.label, ind.source, "N/A", "N/A", "N/A"))
            continue
        unit = {"%": "%", "%p": "%p", "원": "원", "pt": ""}.get(ind.unit, ind.unit)
        change = "N/A"
        if ind.change_6m is not None:
            change = f"{ind.change_6m:+.2f}%p" if ind.change_kind == "diff" else f"{ind.change_6m:+.1f}%"
        rows.append((ind.label, ind.source, fmt_num(ind.latest, 2, unit), ind.latest_date.isoformat(), change))
    return rows


def llm_payload(m_company: str, stock_code: str, ratios: list[YearRatios], val: Valuation, snap: MacroSnapshot,
                sc: ScoreCard, d: dec.Decision, regime: str) -> dict:
    """LLM 에 전달할 구조화 데이터. 수치는 모두 분석 단계에서 계산된 값이다."""
    latest = ratios[-1] if ratios else None
    keep = ("year", "debt_ratio", "current_ratio", "borrowing_dependency", "interest_coverage", "op_margin",
            "net_margin", "roe", "roa", "revenue_growth", "op_growth", "cfo_to_ni", "fcf_margin")
    return {
        "company": m_company,
        "stock_code": stock_code,
        "score": sc.total,
        "grade": d.grade,
        "verdict": d.verdict,
        "limit_pct": d.limit_pct,
        "requested_amount": d.requested_amount,
        "approved_amount": d.approved_amount,
        "categories": [
            {"name": c.name, "weight": round(c.effective_weight, 1), "points": None if c.points is None else round(c.points, 1),
             "ratio": None if c.ratio is None else round(c.ratio, 2)}
            for c in sc.categories
        ],
        "ratios": {k: (None if getattr(latest, k) is None else round(getattr(latest, k), 2)) for k in keep} if latest else {},
        "valuation": {k: (None if v is None else round(v, 2)) for k, v in vars(val).items()},
        "macro": {k: {"latest": i.latest, "change_6m": None if i.change_6m is None else round(i.change_6m, 2)}
                  for k, i in snap.indicators.items()},
        "macro_regime": regime,
        "flags": [f"[{f.level}] {f.title}: {f.detail}" for f in d.flags],
        "covenants": d.covenants,
    }


def build_memo(
    bundle: DataBundle,
    *,
    amount: float,
    portfolio: float,
    provider: LLMProvider,
    provider_note: str | None = None,
    reviewer: str = "자동심사 (invest_memo)",
    today: date | None = None,
    model_name: str = "",
) -> MemoData:
    today = today or date.today()
    ratios = compute_ratios(bundle.financial.years) if bundle.financial else []
    ratios = [r for r in ratios if r.has_data()]
    valuation = compute_valuation(ratios[-1] if ratios else None, bundle.price)
    snap = build_snapshot(bundle.ecos, bundle.fred)
    sc = score(ratios, valuation, snap)
    flags = dec.collect_flags(ratios, bundle.disclosures or [], valuation, snap, sc)
    decision = dec.decide(sc, flags, ratios, valuation, amount, portfolio)

    macro_cat = sc.category("거시환경")
    regime = regime_label(macro_cat.ratio if macro_cat else None)
    payload = llm_payload(bundle.company_name, bundle.stock_code, ratios, valuation, snap, sc, decision, regime)
    opinion, source, fail_note = generate_with_fallback(provider, payload)

    notes = list(bundle.notes)
    if provider_note:
        notes.append(provider_note)
    if fail_note:
        notes.append(fail_note)
    if bundle.disclosures is None:
        notes.append("공시 조회 불가: 공시 기반 녹아웃 검사를 수행하지 못했습니다.")

    fs_label = {"CFS": "연결재무제표", "OFS": "별도재무제표"}.get(bundle.financial.fs_div, "") if bundle.financial else ""
    return MemoData(
        stock_code=bundle.stock_code,
        company_name=bundle.company_name,
        request_date=today,
        requested_amount=amount,
        portfolio_value=portfolio,
        reviewer=reviewer,
        company_rows=_company_rows(bundle),
        shareholders=bundle.shareholders,
        fs_div_label=fs_label,
        fin_years=[r.year for r in ratios],
        fin_amount_rows=_amount_rows(ratios),
        fin_ratio_rows=_ratio_rows(ratios),
        fin_comments=_fin_comments(ratios),
        valuation_rows=_valuation_rows(valuation),
        macro_rows=_macro_rows(snap),
        macro_regime=regime,
        disclosures=bundle.disclosures,
        scorecard=sc,
        decision=decision,
        opinion=opinion,
        opinion_source=source,
        notes=notes,
        is_demo=bundle.is_demo,
        model_name=model_name if source != "규칙 기반" else "",
    )
