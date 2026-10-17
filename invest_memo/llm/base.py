"""LLM 제공자 인터페이스와 규칙 기반 대체 구현."""
from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str

    def generate_opinion(self, payload: dict) -> str:
        """구조화된 심사 데이터(payload)로 심사의견 텍스트를 만든다."""
        ...


def _fmt(v, suffix="", nd=1) -> str:
    return "N/A" if v is None else f"{v:,.{nd}f}{suffix}"


class RuleBasedProvider:
    """템플릿 문장으로 심사의견을 작성한다 (LLM 없이 항상 동작)."""

    name = "규칙 기반"

    def generate_opinion(self, p: dict) -> str:
        r = p.get("ratios") or {}
        lines = [
            f"{p['company']}({p['stock_code']})에 대한 정량 평점은 {p['score']:.1f}점, 내부등급 {p['grade']}이며 "
            f"판정은 '{p['verdict']}'입니다."
        ]
        cats = [c for c in p["categories"] if c["ratio"] is not None]
        if cats:
            best = max(cats, key=lambda c: c["ratio"])
            worst = min(cats, key=lambda c: c["ratio"])
            lines.append(
                f"항목별로는 {best['name']}({best['ratio'] * 100:.0f}%)이 가장 양호하고 "
                f"{worst['name']}({worst['ratio'] * 100:.0f}%)이 가장 취약합니다."
            )
        if r:
            lines.append(
                f"{r['year']}년 기준 부채비율 {_fmt(r.get('debt_ratio'), '%', 0)}, "
                f"영업이익률 {_fmt(r.get('op_margin'), '%')}, ROE {_fmt(r.get('roe'), '%')}, "
                f"매출 성장률 {_fmt(r.get('revenue_growth'), '%')}입니다."
            )
        else:
            lines.append("재무제표 데이터를 확보하지 못해 재무 평가는 제한적입니다.")
        lines.append(f"거시환경은 '{p['macro_regime']}'으로 판단됩니다.")
        if p["flags"]:
            lines.append("주요 리스크: " + "; ".join(p["flags"][:5]) + ".")
        else:
            lines.append("특이한 녹아웃·경고 사항은 확인되지 않았습니다.")
        if p["approved_amount"] > 0:
            lines.append(
                f"신청금액 {p['requested_amount']:,.0f}원 중 {p['approved_amount']:,.0f}원"
                f"(포트폴리오의 {p['limit_pct']:g}% 한도 내)을 승인하며, 승인조건 준수를 전제로 합니다."
            )
        else:
            lines.append("투자한도를 부여하지 않으므로 신규 투자는 권고하지 않습니다.")
        return "\n\n".join(lines)


def generate_with_fallback(provider: LLMProvider, payload: dict) -> tuple[str, str, str | None]:
    """제공자 호출. 실패하면 규칙 기반으로 대체한다. 반환: (의견, 작성주체, 비고)."""
    try:
        text = provider.generate_opinion(payload).strip()
        if not text:
            raise ValueError("빈 응답")
        return text, provider.name, None
    except Exception as exc:  # LLM 오류는 승인서 생성을 막지 않는다
        text = RuleBasedProvider().generate_opinion(payload)
        note = f"{provider.name} 호출 실패({type(exc).__name__})로 규칙 기반 의견으로 대체했습니다."
        return text, RuleBasedProvider.name, note
