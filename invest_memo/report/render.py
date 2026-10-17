"""MemoData → Markdown / HTML 파일."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, PackageLoader

from .builder import MemoData, fmt_num, fmt_won

SECTIONS = [
    "신청개요",
    "기업개요",
    "재무분석",
    "거시환경",
    "최근 주요 공시",
    "리스크 요인",
    "평점표 및 내부등급",
    "심사의견",
    "승인 판정 · 투자한도 · 승인조건",
    "결재란",
]

DISCLAIMER = "본 문서는 공개 데이터와 자동 분석에 기반한 투자 참고용 자료이며, 투자 권유 또는 투자 자문이 아닙니다. 투자 판단과 그 결과에 대한 책임은 투자자 본인에게 있습니다."


def _md_cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("invest_memo.report", "templates"),
        autoescape=lambda name: bool(name) and name.endswith(".html.j2"),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(won=fmt_won, num=fmt_num, mdcell=_md_cell)
    env.globals.update(SECTIONS=SECTIONS, DISCLAIMER=DISCLAIMER)
    return env


def render_markdown(memo: MemoData) -> str:
    return _env().get_template("memo.md.j2").render(m=memo)


def render_html(memo: MemoData) -> str:
    return _env().get_template("memo.html.j2").render(m=memo)


def write_reports(memo: MemoData, out_dir: str | Path, formats=("md", "html")) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{memo.stock_code}_{memo.request_date:%Y%m%d}"
    renderers = {"md": render_markdown, "html": render_html}
    paths = []
    for fmt in formats:
        path = out / f"{stem}.{fmt}"
        path.write_text(renderers[fmt](memo), encoding="utf-8")
        paths.append(path)
    return paths
