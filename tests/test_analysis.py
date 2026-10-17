from datetime import date, timedelta

import pytest

from invest_memo.analysis import decision as dec
from invest_memo.analysis.financials import Valuation, YearRatios, compute_ratios, compute_valuation
from invest_memo.analysis.macro import build_snapshot, regime_label
from invest_memo.analysis.scoring import WEIGHTS, grade_for, lookup, score, DEBT_RATIO, OP_MARGIN
from invest_memo.sources import Observation
from invest_memo.sources.dart import Disclosure
from invest_memo.sources.price import price_info_from_closes


def yrs(**kw):
    base = dict(revenue=1000, operating_income=100, net_income=80, total_assets=1000, total_liabilities=400,
                total_equity=600, current_assets=500, current_liabilities=250, borrowings=100,
                interest_expense=10, cfo=120, capex=50, paid_in_capital=100)
    base.update(kw)
    return base


def test_ratios_basic_and_growth():
    r = compute_ratios({2023: yrs(revenue=800), 2024: yrs(revenue=900), 2025: yrs(revenue=1000)})
    assert [x.year for x in r] == [2023, 2024, 2025]
    cur = r[-1]
    assert cur.debt_ratio == pytest.approx(400 / 600 * 100)
    assert cur.current_ratio == 200
    assert cur.interest_coverage == 10
    assert cur.revenue_growth == pytest.approx(100 / 900 * 100)
    assert cur.fcf == 70 and cur.cfo_to_ni == 1.5
    assert r[0].revenue_growth is None  # 직전연도 없음


def test_ratios_handle_missing_and_zero():
    r = compute_ratios({2025: yrs(total_equity=0, interest_expense=None, net_income=-5, revenue=None)})[0]
    assert r.debt_ratio is None and r.interest_coverage is None
    assert r.cfo_to_ni is None  # 순손실이면 의미 없음
    assert r.op_margin is None


def test_valuation_without_price_is_empty():
    v = compute_valuation(None, None)
    assert v.per is None and v.volatility is None


def test_valuation_with_market_cap():
    r = compute_ratios({2025: yrs()})[0]
    p = price_info_from_closes([100, 110, 105, 120], market_cap=800)
    v = compute_valuation(r, p)
    assert v.per == 10 and v.pbr == pytest.approx(800 / 600)
    assert v.drawdown == 0 and v.volatility > 0


def test_lookup_boundaries():
    assert lookup(50, DEBT_RATIO, False) == 1  # 경계 포함
    assert lookup(50.01, DEBT_RATIO, False) == .8
    assert lookup(301, DEBT_RATIO, False) == 0
    assert lookup(0, OP_MARGIN, True) == .2
    assert lookup(-0.1, OP_MARGIN, True) == 0
    assert lookup(None, OP_MARGIN, True) is None


@pytest.mark.parametrize("total,grade", [(95, "A+"), (90, "A+"), (89.9, "A"), (80, "A"), (79.9, "B+"), (70, "B+"),
                                         (69.9, "B"), (60, "B"), (59.9, "C"), (50, "C"), (49.9, "D")])
def test_grade_boundaries(total, grade):
    assert grade_for(total) == grade


def good_macro():
    today = date(2026, 10, 1)
    daily = lambda vals: [Observation(today - timedelta(days=60 * (len(vals) - 1 - i)), v) for i, v in enumerate(vals)]
    return build_snapshot(
        {"kr_base_rate": daily([3.0, 3.0, 2.75, 2.5]), "usdkrw": daily([1400, 1380, 1360, 1350])},
        {"fed_funds": daily([4.5, 4.25, 4.0, 3.75]), "vix": daily([15]), "t10y2y": daily([0.5])},
    )


def test_score_weights_sum_and_redistribution():
    assert sum(WEIGHTS.values()) == 100
    ratios = compute_ratios({2024: yrs(revenue=900), 2025: yrs()})
    full = score(ratios, Valuation(per=10, pbr=1, volatility=25), good_macro())
    assert full.total <= 100 and sum(c.effective_weight for c in full.categories) == pytest.approx(100)
    partial = score(ratios, Valuation(), None)  # 밸류에이션·거시 N/A
    val = partial.category("밸류에이션")
    assert val.points is None and val.effective_weight == 0
    assert sum(c.effective_weight for c in partial.categories) == pytest.approx(100)
    assert any("밸류에이션" in n for n in partial.notes)


def test_score_with_no_data_at_all():
    sc = score([], Valuation(), None)
    assert sc.grade == "N/A" and sc.total == 0


def test_macro_snapshot_missing_series_is_na():
    snap = build_snapshot({}, {})
    assert snap.value("vix") is None
    assert regime_label(None).startswith("판단불가")


def test_macro_change_and_yoy():
    today = date(2026, 10, 1)
    cpi = [Observation(date(2025, 9, 1), 100.0), Observation(date(2026, 9, 1), 103.0)]
    snap = build_snapshot({"kr_cpi": cpi}, {})
    assert snap.value("kr_cpi") == pytest.approx(3.0)
    snap = build_snapshot({"usdkrw": [Observation(date(2026, 3, 1), 1300.0), Observation(date(2026, 9, 1), 1430.0)]}, {})
    assert snap.value("usdkrw", "change_6m") == pytest.approx(10.0)
    assert today  # silence


def _decide(ratios_years, disclosures=(), amount=10_000_000, portfolio=100_000_000, macro=None, val=None):
    ratios = compute_ratios(ratios_years)
    val = val or Valuation(per=10, pbr=1, volatility=25)
    sc = score(ratios, val, macro or good_macro())
    flags = dec.collect_flags(ratios, list(disclosures), val, macro or good_macro(), sc)
    return dec.decide(sc, flags, ratios, val, amount, portfolio), sc


GOOD = {2024: yrs(revenue=900, operating_income=80), 2025: yrs(revenue=1100, operating_income=200, net_income=150)}


def test_decision_approve_and_reduce():
    d, sc = _decide(GOOD, amount=20_000_000)
    assert d.verdict == dec.APPROVE and d.limit_pct in (7, 10)
    assert d.reduced and d.approved_amount == 100_000_000 * d.limit_pct / 100
    assert any("분할" in c for c in d.covenants) is False
    assert d.stop_loss_pct is not None and 8 <= d.stop_loss_pct <= 15


def test_decision_policy_table():
    for grade, (verdict, limit) in {"B": (dec.CONDITIONAL, 5), "C": (dec.HOLD, 0), "D": (dec.REJECT, 0)}.items():
        assert dec.GRADE_POLICY[grade] == (verdict, limit)


def test_conditional_has_split_buy():
    covs, stop = dec.build_covenants(dec.CONDITIONAL, None, Valuation(volatility=100))
    assert any("분할매수" in c for c in covs) and stop == 15
    covs, stop = dec.build_covenants(dec.APPROVE, None, Valuation(volatility=5))
    assert stop == 8
    assert dec.build_covenants(dec.APPROVE, None, Valuation())[1] == 10


def test_knockout_capital_impairment_rejects():
    years = dict(GOOD)
    years[2025] = yrs(total_equity=50, paid_in_capital=100)
    d, _ = _decide(years)
    assert d.verdict == dec.REJECT and d.grade == "D" and d.approved_amount == 0


def test_knockout_two_year_operating_loss_downgrades():
    years = {2024: yrs(operating_income=-10), 2025: yrs(operating_income=-5)}
    d, _ = _decide(years)
    assert d.verdict in (dec.HOLD, dec.REJECT) and d.approved_amount == 0
    assert any(f.title == "2년 연속 영업적자" for f in d.flags)


def test_knockout_interest_coverage_two_years():
    years = {2024: yrs(operating_income=5, interest_expense=10), 2025: yrs(operating_income=8, interest_expense=10)}
    d, _ = _decide(years)
    assert any("이자보상배율" in f.title and f.level == "downgrade" for f in d.flags)
    assert d.verdict != dec.APPROVE


def test_knockout_disclosure_keyword():
    ds = [Disclosure("2026-09-01", "횡령ㆍ배임사실확인", "x", "1"), Disclosure("2026-09-02", "분기보고서", "x", "2")]
    d, _ = _decide(GOOD, disclosures=ds)
    assert d.verdict == dec.REJECT
    d2, _ = _decide(GOOD, disclosures=[Disclosure("2026-09-02", "불성실공시법인 지정예고", "x", "2")])
    assert d2.verdict == dec.APPROVE and any(f.level == "warning" for f in d2.flags)


def test_no_data_holds():
    d, sc = _decide({}, val=Valuation(), macro=build_snapshot({}, {}))
    assert d.verdict == dec.HOLD and d.approved_amount == 0
