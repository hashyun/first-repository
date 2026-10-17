from __future__ import annotations

from ..config import Settings
from .base import LLMProvider, RuleBasedProvider, generate_with_fallback

__all__ = ["LLMProvider", "RuleBasedProvider", "generate_with_fallback", "get_provider"]


def get_provider(settings: Settings, use_llm: bool = True) -> tuple[LLMProvider, str | None]:
    """설정에 맞는 제공자를 반환한다. 반환: (제공자, 규칙 기반으로 떨어진 이유 또는 None)."""
    if not use_llm:
        return RuleBasedProvider(), None
    if not settings.anthropic_api_key:
        return RuleBasedProvider(), "ANTHROPIC_API_KEY 가 없어 규칙 기반 의견을 사용했습니다."
    try:
        from .claude import ClaudeProvider

        return ClaudeProvider(settings.anthropic_api_key, settings.llm_model), None
    except Exception as exc:  # anthropic 미설치 등
        return RuleBasedProvider(), f"Claude 초기화 실패({type(exc).__name__})로 규칙 기반 의견을 사용했습니다."
