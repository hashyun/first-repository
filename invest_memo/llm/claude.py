"""Claude(anthropic SDK) 기반 심사의견 작성."""
from __future__ import annotations

import json

try:  # 선택 의존성
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

SYSTEM_PROMPT = (
    "당신은 은행 여신심사부의 심사역입니다. 주식 투자 건을 여신 심사하듯 검토하여 "
    "승인서의 '심사의견' 항목을 한국어로 작성합니다.\n"
    "규칙:\n"
    "1. 반드시 사용자가 제공한 JSON 데이터에 있는 사실과 수치만 사용합니다. 없는 수치를 만들거나 추정하지 마세요.\n"
    "2. 값이 null 이거나 'N/A' 인 항목은 '데이터 없음'으로 명시하고 해석하지 않습니다.\n"
    "3. 이미 확정된 판정(verdict)·등급·한도를 바꾸지 말고, 그 근거를 설명합니다.\n"
    "4. 구성: 종합의견 → 강점 → 우려사항 → 승인조건 이행 시 유의점. 전체 6~10문장, 간결한 문어체.\n"
    "5. 투자 권유 표현은 피하고 심사 의견의 어조를 유지합니다."
)


class ClaudeProvider:
    name = "Claude"

    def __init__(self, api_key: str, model: str, max_tokens: int = 1500, client=None):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            if anthropic is None:
                raise RuntimeError("anthropic 패키지가 설치되어 있지 않습니다.")
            client = anthropic.Anthropic(api_key=api_key)
        self.client = client

    def generate_opinion(self, payload: dict) -> str:
        user = "아래 심사 데이터를 바탕으로 심사의견을 작성하세요.\n\n" + json.dumps(
            payload, ensure_ascii=False, indent=2
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
