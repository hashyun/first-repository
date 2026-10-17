import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, json_data=None, content: bytes = b"", status: int = 200):
        self._json, self.content, self.status_code = json_data, content, status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture
def fake_get(monkeypatch):
    """requests.get 을 대체한다. handler(url, params) -> FakeResponse. 호출 기록은 calls 에 쌓인다."""
    calls = []

    def install(handler):
        def _get(url, params=None, timeout=None, **kw):
            calls.append((url, params))
            return handler(url, params)

        monkeypatch.setattr("requests.get", _get)
        monkeypatch.setattr("time.sleep", lambda s: None)
        return calls

    return install
