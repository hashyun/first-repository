from datetime import date

import pytest

from invest_memo.cli import main
from invest_memo.config import Settings
from invest_memo.demo_data import load_demo
from invest_memo.llm import RuleBasedProvider
from invest_memo.report.builder import DataBundle, build_memo, collect_live
from invest_memo.report.render import SECTIONS, render_html, render_markdown

from conftest import FakeResponse, load_fixture
from test_llm import FakeClient, PAYLOAD  # noqa: F401
from invest_memo.llm.claude import ClaudeProvider

TODAY = date(2026, 10, 17)


def memo_for(bundle, **kw):
    return build_memo(bundle, amount=1e7, portfolio=1e8, provider=kw.pop("provider", RuleBasedProvider()), today=TODAY, **kw)


def assert_complete(text):
    for i, name in enumerate(SECTIONS, 1):
        assert name in text, name
    assert "결재란" in text and "담당" in text and "심사역" in text and "승인권자" in text
    assert "투자 권유" in text


def test_demo_memo_has_all_sections():
    m = memo_for(load_demo(TODAY))
    md, html = render_markdown(m), render_html(m)
    assert_complete(md)
    assert_complete(html)
    assert "N/A" not in md.split("## 7.")[0].split("## 3.")[1].split("매출 성장률")[0]
    assert html.startswith("<!doctype html>") and "@media print" in html
    assert m.decision.verdict in ("승인", "조건부승인")


def test_empty_bundle_renders_with_na():
    m = memo_for(DataBundle(stock_code="005930", company_name="005930"))
    md = render_markdown(m)
    assert_complete(md)
    assert "N/A" in md and m.decision.verdict == "보류" and m.decision.approved_amount == 0
    assert_complete(render_html(m))


def test_llm_failure_is_noted_in_memo():
    m = memo_for(load_demo(TODAY), provider=ClaudeProvider("k", "m", client=FakeClient(fail=True)))
    md = render_markdown(m)
    assert "규칙 기반" in md and "호출 실패" in md


def test_llm_success_is_used():
    m = memo_for(load_demo(TODAY), provider=ClaudeProvider("k", "m", client=FakeClient(text="LLM이 쓴 의견")), model_name="m")
    md = render_markdown(m)
    assert "LLM이 쓴 의견" in md and "Claude (m)" in md


def test_html_escapes_content():
    b = load_demo(TODAY)
    b.company_name = "<script>x</script>"
    assert "<script>x</script>" not in render_html(memo_for(b))


def test_collect_live_without_keys_degrades(monkeypatch, tmp_path):
    monkeypatch.setattr("invest_memo.report.builder.fetch_price_info", lambda code, today: None)
    b = collect_live(Settings(cache_dir=tmp_path), "005930", 2025, TODAY)
    assert b.financial is None and len(b.notes) == 4
    assert_complete(render_markdown(memo_for(b)))


def test_collect_live_with_fixtures(fake_get, monkeypatch, tmp_path):
    from conftest import FIXTURES

    def handler(url, p):
        if "corpCode.xml" in url:
            return FakeResponse(content=(FIXTURES / "corpcode.zip").read_bytes())
        if "opendart" in url:
            name = {"company.json": "dart_company.json", "fnlttSinglAcntAll.json": "dart_fnltt.json",
                    "list.json": "dart_list.json", "hyslrSttus.json": "dart_hyslr.json"}[url.rsplit("/", 1)[1]]
            return FakeResponse(load_fixture(name))
        if "ecos" in url:
            return FakeResponse(load_fixture("ecos_ok.json"))
        return FakeResponse(load_fixture("fred_ok.json"))

    fake_get(handler)
    monkeypatch.setattr("invest_memo.report.builder.fetch_price_info", lambda code, today: None)
    s = Settings(dart_api_key="a", ecos_api_key="b", fred_api_key="c", cache_dir=tmp_path)
    b = collect_live(s, "005930", 2025, TODAY)
    assert b.company_name == "테스트전자" and b.financial.fs_div == "CFS"
    m = memo_for(b)
    md = render_markdown(m)
    assert_complete(md)
    assert m.decision.verdict == "거절"  # 픽스처 공시에 횡령/배임 키워드
    assert "공시 키워드" in md


def test_cli_demo_writes_files(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["--demo", "--out", str(tmp_path / "reports")]) == 0
    files = sorted(p.name for p in (tmp_path / "reports").iterdir())
    assert [f.rsplit(".", 1)[1] for f in files] == ["html", "md"]
    assert files[0].startswith("000000_")
    assert "판정" in capsys.readouterr().out


def test_cli_format_and_validation(tmp_path, capsys):
    assert main(["--demo", "--no-llm", "--format", "md", "--out", str(tmp_path)]) == 0
    assert [p.suffix for p in tmp_path.iterdir()] == [".md"]
    for bad in (["--stock", "12"], ["--demo", "--format", "pdf"], []):
        with pytest.raises(SystemExit):
            main(bad)
