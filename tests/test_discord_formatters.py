"""Unit tests for the pure Discord embed formatting helpers."""
from discord_notifier import _format_skills_for_field, _format_language_for_field


def test_format_skills_empty_returns_none():
    assert _format_skills_for_field([]) is None
    assert _format_skills_for_field(None) is None


def test_format_skills_renders_star_levels():
    out = _format_skills_for_field([{"skill": "Python", "level": 3}])
    assert "Python" in out
    assert "★★★" in out


def test_format_skills_without_level_has_no_stars():
    assert _format_skills_for_field([{"skill": "Bash"}]) == "• Bash"


def test_format_skills_truncates_to_discord_limit():
    many = [{"skill": "S" * 50, "level": 1} for _ in range(100)]
    out = _format_skills_for_field(many)
    # Discord field limit is 1024; helper cuts to 1020 and appends an ellipsis.
    assert len(out) <= 1023
    assert out.endswith("...")


def test_format_language_capitalizes_level():
    assert _format_language_for_field([{"name": "English", "level": "c1"}]) == "• English: C1"


def test_format_language_empty_returns_none():
    assert _format_language_for_field([]) is None
