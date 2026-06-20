"""Tests for the relevance scoring layer (rules backend + dispatcher)."""
import json

import relevance
from relevance import score_with_rules, load_rules


def _offer(**overrides):
    base = {
        "id": 1,
        "position": "Backend Engineer",
        "company": {"name": "ACME"},
        "remotePercentage": 100,
        "salaryFrom": 40000,
        "salaryTo": 60000,
        "locations": ["Madrid"],
    }
    base.update(overrides)
    return base


SKILLS = {"must": [{"skill": "Python"}], "nice": [{"skill": "Docker"}], "extra": []}


# --- score_with_rules ------------------------------------------------------

def test_empty_rules_passes_with_base_score():
    result = score_with_rules(_offer(), SKILLS, [], {})
    assert result["relevant"] is True
    assert result["score"] == 60


def test_excluded_skill_fails():
    result = score_with_rules(_offer(), SKILLS, [], {"excluded_skills": ["Python"]})
    assert result["relevant"] is False
    assert result["score"] == 0
    assert "excluded skill" in result["reason"]


def test_min_salary_not_met_fails():
    result = score_with_rules(_offer(salaryFrom=20000, salaryTo=30000), SKILLS, [], {"min_salary": 40000})
    assert result["relevant"] is False


def test_min_salary_unknown_passes():
    result = score_with_rules(_offer(salaryFrom=None, salaryTo=None), SKILLS, [], {"min_salary": 40000})
    assert result["relevant"] is True


def test_required_skills_matched_boosts_score():
    result = score_with_rules(_offer(), SKILLS, [], {"required_skills_any": ["Python", "Go"]})
    assert result["relevant"] is True
    assert result["score"] == 70
    assert "python" in result["reason"].lower()


def test_required_skills_none_present_fails():
    result = score_with_rules(_offer(), SKILLS, [], {"required_skills_any": ["Rust"]})
    assert result["relevant"] is False


def test_position_excludes_fails():
    result = score_with_rules(_offer(position="Senior Consultant"), SKILLS, [], {"position_excludes": ["Consultant"]})
    assert result["relevant"] is False


def test_min_remote_not_met_fails():
    result = score_with_rules(_offer(remotePercentage=0), SKILLS, [], {"min_remote_percentage": 50})
    assert result["relevant"] is False


def test_locations_any_matches_and_misses():
    assert score_with_rules(_offer(locations=["Madrid"]), SKILLS, [], {"locations_any": ["Madrid", "Remote"]})["relevant"]
    assert not score_with_rules(_offer(locations=["Barcelona"]), SKILLS, [], {"locations_any": ["Madrid"]})["relevant"]


def test_excluded_company_fails():
    result = score_with_rules(_offer(company={"name": "Big Consulting SL"}), SKILLS, [], {"excluded_companies": ["Consulting"]})
    assert result["relevant"] is False


# --- load_rules ------------------------------------------------------------

def test_load_rules_missing_file_returns_empty(tmp_path):
    assert load_rules(str(tmp_path / "nope.json")) == {}


def test_load_rules_reads_json(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text('{"min_salary": 1000}')
    assert load_rules(str(path)) == {"min_salary": 1000}


# --- dispatcher ------------------------------------------------------------

def test_dispatch_off_returns_none(monkeypatch):
    monkeypatch.setitem(relevance.CONFIG, "FILTER_MODE", "off")
    assert relevance.score_offer(_offer(), SKILLS, []) is None


def test_dispatch_rules_uses_configured_file(monkeypatch, tmp_path):
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps({"excluded_skills": ["Python"]}))
    monkeypatch.setitem(relevance.CONFIG, "FILTER_MODE", "rules")
    monkeypatch.setitem(relevance.CONFIG, "FILTER_RULES_PATH", str(rules_file))
    result = relevance.score_offer(_offer(), SKILLS, [])
    assert result is not None and result["relevant"] is False


def test_dispatch_ai_without_backend_returns_none(monkeypatch):
    # The AI backend module is added in a later change; until then 'ai' degrades to None.
    monkeypatch.setitem(relevance.CONFIG, "FILTER_MODE", "ai")
    assert relevance.score_offer(_offer(), SKILLS, []) is None
