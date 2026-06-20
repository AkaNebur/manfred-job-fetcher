"""Tests for the AI relevance backend, with the Anthropic client mocked (no network)."""
import relevance
import relevance_ai
from relevance_ai import score_with_ai, RelevanceVerdict, _format_offer


class FakeResponse:
    def __init__(self, verdict):
        self.parsed_output = verdict


class FakeMessages:
    def __init__(self, verdict=None, exc=None):
        self._verdict = verdict
        self._exc = exc
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return FakeResponse(self._verdict)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages


OFFER = {
    "id": 1,
    "position": "Backend Engineer",
    "company": {"name": "ACME"},
    "remotePercentage": 100,
    "salaryFrom": 40000,
    "salaryTo": 60000,
    "locations": ["Madrid"],
}
SKILLS = {"must": [{"skill": "Python"}], "nice": [], "extra": []}


def test_score_with_ai_returns_verdict(monkeypatch):
    fake = FakeClient(FakeMessages(verdict=RelevanceVerdict(relevant=True, score=82, reason="Python backend, remote")))
    monkeypatch.setattr(relevance_ai, "_get_client", lambda: fake)

    result = score_with_ai(OFFER, SKILLS, [])
    assert result == {"relevant": True, "score": 82, "reason": "Python backend, remote"}

    # Structured output and the configured model were requested.
    call = fake.messages.calls[0]
    assert call["model"] == relevance_ai.CONFIG["AI_MODEL"]
    assert call["output_format"] is RelevanceVerdict


def test_score_with_ai_no_client_returns_none(monkeypatch):
    monkeypatch.setattr(relevance_ai, "_get_client", lambda: None)
    assert score_with_ai(OFFER, SKILLS, []) is None


def test_score_with_ai_handles_api_error(monkeypatch):
    fake = FakeClient(FakeMessages(exc=RuntimeError("boom")))
    monkeypatch.setattr(relevance_ai, "_get_client", lambda: fake)
    assert score_with_ai(OFFER, SKILLS, []) is None


def test_load_profile_prefers_env_over_file(monkeypatch, tmp_path):
    path = tmp_path / "profile.md"
    path.write_text("From file")
    monkeypatch.setitem(relevance_ai.CONFIG, "AI_PROFILE_PATH", str(path))
    monkeypatch.setitem(relevance_ai.CONFIG, "AI_USER_PROFILE", "From env")
    assert relevance_ai._load_profile() == "From env"


def test_load_profile_reads_file_when_env_empty(monkeypatch, tmp_path):
    path = tmp_path / "profile.md"
    path.write_text("Backend Python, remote")
    monkeypatch.setitem(relevance_ai.CONFIG, "AI_USER_PROFILE", "")
    monkeypatch.setitem(relevance_ai.CONFIG, "AI_PROFILE_PATH", str(path))
    assert relevance_ai._load_profile() == "Backend Python, remote"


def test_format_offer_includes_key_fields():
    text = _format_offer(OFFER, SKILLS, [{"name": "English", "level": "C1"}])
    assert "Backend Engineer" in text
    assert "ACME" in text
    assert "Python" in text
    assert "English" in text


def test_dispatcher_routes_ai_mode(monkeypatch):
    monkeypatch.setitem(relevance.CONFIG, "FILTER_MODE", "ai")
    monkeypatch.setattr(relevance_ai, "score_with_ai",
                        lambda offer, skills, languages: {"relevant": True, "score": 99, "reason": "x"})
    assert relevance.score_offer(OFFER, SKILLS, []) == {"relevant": True, "score": 99, "reason": "x"}
