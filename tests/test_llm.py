import json
from types import SimpleNamespace

from invest_memo.config import DEFAULT_LLM_MODEL, Settings, load_settings
from invest_memo.llm import RuleBasedProvider, generate_with_fallback, get_provider
from invest_memo.llm.claude import SYSTEM_PROMPT, ClaudeProvider

PAYLOAD = {
    "company": "테스트", "stock_code": "000000", "score": 72.0, "grade": "B+", "verdict": "승인", "limit_pct": 7,
    "requested_amount": 1e7, "approved_amount": 7e6, "macro_regime": "중립", "flags": [], "covenants": [],
    "ratios": {"year": 2025, "debt_ratio": None, "op_margin": 10.0, "roe": None, "revenue_growth": 5.0},
    "categories": [{"name": "수익성", "ratio": 0.8}, {"name": "밸류에이션", "ratio": None}],
}


class FakeClient:
    def __init__(self, text="의견 본문", fail=False):
        self.calls, self.fail, self.text = [], fail, text
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("boom")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_claude_provider_request_shape():
    client = FakeClient()
    out = ClaudeProvider("k", "claude-sonnet-5-5", client=client).generate_opinion(PAYLOAD)
    assert out == "의견 본문"
    kw = client.calls[0]
    assert kw["model"] == "claude-sonnet-5-5" and kw["system"] == SYSTEM_PROMPT and kw["max_tokens"] > 0
    assert kw["messages"][0]["role"] == "user" and json.dumps(PAYLOAD["company"], ensure_ascii=False) in kw["messages"][0]["content"]


def test_fallback_on_llm_error():
    text, source, note = generate_with_fallback(ClaudeProvider("k", "m", client=FakeClient(fail=True)), PAYLOAD)
    assert source == "규칙 기반" and "대체" in note and "테스트" in text


def test_fallback_on_empty_response():
    _, source, note = generate_with_fallback(ClaudeProvider("k", "m", client=FakeClient(text="  ")), PAYLOAD)
    assert source == "규칙 기반" and note


def test_rule_based_handles_missing_values():
    text = RuleBasedProvider().generate_opinion(PAYLOAD)
    assert "N/A" in text and "승인" in text


def test_get_provider_selection():
    s = Settings()
    assert isinstance(get_provider(s, use_llm=False)[0], RuleBasedProvider)
    p, note = get_provider(s, use_llm=True)
    assert isinstance(p, RuleBasedProvider) and "ANTHROPIC_API_KEY" in note
    p, note = get_provider(Settings(anthropic_api_key="x", llm_model="m"), use_llm=True)
    assert note is None and p.name == "Claude" and p.model == "m"


def test_llm_model_env(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("DART_API_KEY", "  ")
    assert load_settings(env_file="/nonexistent").llm_model == DEFAULT_LLM_MODEL == "claude-sonnet-5-5"
    assert load_settings(env_file="/nonexistent").dart_api_key is None
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    assert load_settings(env_file="/nonexistent").llm_model == "custom-model"
