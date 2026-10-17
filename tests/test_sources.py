from datetime import date

import pytest

from invest_memo.cache import FileCache
from invest_memo.sources import SourceError
from invest_memo.sources.dart import DartClient, parse_amount
from invest_memo.sources.ecos import EcosClient
from invest_memo.sources.fred import FredClient

from conftest import FIXTURES, FakeResponse, load_fixture


def test_parse_amount():
    assert parse_amount("1,234") == 1234
    assert parse_amount("-1,234") == -1234
    assert parse_amount("-") is None
    assert parse_amount("") is None
    assert parse_amount(None) is None


def test_dart_find_corp_from_zip(fake_get):
    zip_bytes = (FIXTURES / "corpcode.zip").read_bytes()
    calls = fake_get(lambda url, p: FakeResponse(content=zip_bytes))
    client = DartClient("KEY")
    corp = client.find_corp("005930")
    assert (corp.corp_code, corp.corp_name) == ("00126380", "테스트전자")
    assert calls[0][0].endswith("/corpCode.xml") and calls[0][1] == {"crtfc_key": "KEY"}
    with pytest.raises(SourceError):
        client.find_corp("000001")


def test_dart_corpcode_error_is_not_zip(fake_get):
    fake_get(lambda url, p: FakeResponse(content=b"<result><status>010</status></result>"))
    with pytest.raises(SourceError):
        DartClient("BAD").find_corp("005930")


def test_dart_financials_parsing_and_params(fake_get):
    calls = fake_get(lambda url, p: FakeResponse(load_fixture("dart_fnltt.json")))
    fs = DartClient("KEY").financials("00126380", 2025)
    assert fs.fs_div == "CFS"
    params = calls[0][1]
    assert params["reprt_code"] == "11011" and params["fs_div"] == "CFS" and params["bsns_year"] == 2025
    y25, y23 = fs.years[2025], fs.years[2023]
    assert y25["revenue"] == 2000 and y25["operating_income"] == 200
    assert y25["borrowings"] == 80  # 단기 + 장기 (account_nm 매칭)
    assert y25["interest_expense"] == 20  # FinanceCosts 로 대체
    assert y25["capex"] == 100 and y25["cfo"] == 250
    assert y23["operating_income"] == -50
    assert y23["borrowings"] == 40  # '-' 는 결측


def test_dart_financials_falls_back_to_ofs(fake_get):
    def handler(url, p):
        if p["fs_div"] == "CFS":
            return FakeResponse(load_fixture("dart_none.json"))
        return FakeResponse(load_fixture("dart_fnltt.json"))

    fake_get(handler)
    assert DartClient("KEY").financials("1", 2025).fs_div == "OFS"


def test_dart_no_data_everywhere_raises(fake_get):
    fake_get(lambda url, p: FakeResponse(load_fixture("dart_none.json")))
    with pytest.raises(SourceError):
        DartClient("KEY").financials("1", 2025)


def test_dart_error_status(fake_get):
    fake_get(lambda url, p: FakeResponse(load_fixture("dart_error.json")))
    with pytest.raises(SourceError, match="010"):
        DartClient("KEY").company("1")


def test_dart_disclosures_and_shareholders(fake_get):
    def handler(url, p):
        name = "dart_list.json" if url.endswith("/list.json") else "dart_hyslr.json"
        return FakeResponse(load_fixture(name))

    calls = fake_get(handler)
    client = DartClient("KEY")
    ds = client.disclosures("1", 90, today=date(2026, 10, 1))
    assert ds[1].date == "2026-09-01" and "횡령" in ds[1].title
    assert calls[0][1]["bgn_de"] == "20260703" and calls[0][1]["end_de"] == "20261001"
    sh = client.major_shareholders("1", 2025)
    assert [s.name for s in sh] == ["갑", "소액주주"]  # 우선주 제외, 지분율 순
    assert sh[0].ratio == 20.5


def test_ecos_url_form_and_parsing(fake_get):
    calls = fake_get(lambda url, p: FakeResponse(load_fixture("ecos_ok.json")))
    obs = EcosClient("KEY").statistic("722Y001", "M", date(2026, 4, 1), date(2026, 6, 30), "0101000")
    assert calls[0][0] == "https://ecos.bok.or.kr/api/StatisticSearch/KEY/json/kr/1/100/722Y001/M/202604/202606/0101000"
    assert [(o.date, o.value) for o in obs] == [(date(2026, 4, 1), 2.75), (date(2026, 5, 1), 2.75)]  # '-' 제외


def test_ecos_no_data_and_error(fake_get):
    fake_get(lambda url, p: FakeResponse(load_fixture("ecos_nodata.json")))
    assert EcosClient("KEY").series("kr_base_rate", date(2026, 1, 1), date(2026, 6, 1)) == []
    fake_get(lambda url, p: FakeResponse(load_fixture("ecos_error.json")))
    with pytest.raises(SourceError, match="INFO-100"):
        EcosClient("KEY").series("kr_base_rate", date(2026, 1, 1), date(2026, 6, 1))


def test_fred_skips_missing_values(fake_get):
    calls = fake_get(lambda url, p: FakeResponse(load_fixture("fred_ok.json")))
    obs = FredClient("KEY").series("fed_funds", date(2026, 9, 1))
    assert [o.value for o in obs] == [4.33, 4.40]
    assert calls[0][1]["series_id"] == "DFF" and calls[0][1]["file_type"] == "json"


def test_fred_error_does_not_leak_key(fake_get):
    fake_get(lambda url, p: FakeResponse(load_fixture("fred_error.json")))
    with pytest.raises(SourceError, match="api_key"):
        FredClient("SECRET").series("vix", date(2026, 9, 1))


def test_http_failure_is_sanitized_and_retried(fake_get):
    calls = fake_get(lambda url, p: FakeResponse(status=500))
    with pytest.raises(SourceError) as e:
        FredClient("SECRET").series("vix", date(2026, 9, 1))
    assert "SECRET" not in str(e.value) and len(calls) == 3


def test_cache_prevents_second_call(fake_get, tmp_path):
    calls = fake_get(lambda url, p: FakeResponse(load_fixture("fred_ok.json")))
    client = FredClient("KEY", FileCache(tmp_path))
    client.series("vix", date(2026, 9, 1))
    client.series("vix", date(2026, 9, 1))
    assert len(calls) == 1
