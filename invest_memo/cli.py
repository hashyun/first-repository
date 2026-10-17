"""명령행 인터페이스: python -m invest_memo --stock 005930 ..."""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .config import load_settings
from .llm import get_provider
from .report.builder import build_memo, collect_live
from .report.render import write_reports


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="invest_memo",
        description="주식 투자심사 승인서(은행 여신심사 승인서 형식) 생성기. 투자 참고용이며 투자 권유가 아닙니다.",
    )
    p.add_argument("--stock", help="종목코드 6자리 (예: 005930). --demo 사용 시 생략 가능")
    p.add_argument("--amount", type=float, default=10_000_000, help="신청금액(원), 기본 10,000,000")
    p.add_argument("--portfolio", type=float, default=100_000_000, help="포트폴리오 규모(원), 기본 100,000,000")
    p.add_argument("--year", type=int, default=None, help="기준 사업연도 (기본: 작년)")
    p.add_argument("--no-llm", action="store_true", help="LLM 을 쓰지 않고 규칙 기반 심사의견 사용")
    p.add_argument("--format", default="md,html", help="출력 형식, 쉼표 구분 (md,html)")
    p.add_argument("--out", default="reports/", help="출력 디렉터리, 기본 reports/")
    p.add_argument("--reviewer", default="자동심사 (invest_memo)", help="심사자 이름")
    p.add_argument("--demo", action="store_true", help="API 키 없이 번들된 가상 데이터로 실행")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    if not formats or any(f not in ("md", "html") for f in formats):
        parser.error("--format 은 md, html 중에서 쉼표로 지정하세요.")
    if args.amount <= 0 or args.portfolio <= 0:
        parser.error("--amount, --portfolio 는 0보다 커야 합니다.")
    if not args.demo and not (args.stock and args.stock.isdigit() and len(args.stock) == 6):
        parser.error("--stock 에 6자리 종목코드를 지정하세요 (또는 --demo).")

    settings = load_settings()
    today = date.today()
    provider, provider_note = get_provider(settings, use_llm=not args.no_llm)

    if args.demo:
        from .demo_data import load_demo

        bundle = load_demo(today)
    else:
        bundle = collect_live(settings, args.stock, args.year or today.year - 1, today)

    memo = build_memo(
        bundle,
        amount=args.amount,
        portfolio=args.portfolio,
        provider=provider,
        provider_note=provider_note,
        reviewer=args.reviewer,
        today=today,
        model_name=settings.llm_model,
    )
    paths = write_reports(memo, args.out, formats)

    d = memo.decision
    print(f"{memo.company_name}({memo.stock_code}) 판정: {d.verdict} / 등급 {d.grade} / 평점 {d.score:.1f}점 / 승인금액 {d.approved_amount:,.0f}원")
    for path in paths:
        print(f"저장: {path}")
    for note in memo.notes:
        print(f"참고: {note}", file=sys.stderr)
    return 0
