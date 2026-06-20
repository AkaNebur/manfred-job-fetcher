"""Tests for CORS origin parsing in config.load_config()."""
import config


def test_cors_default_is_wildcard(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert config.load_config()["CORS_ALLOW_ORIGINS"] == ["*"]


def test_cors_comma_list_is_split_and_trimmed(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", " https://a.com , https://b.com ")
    assert config.load_config()["CORS_ALLOW_ORIGINS"] == ["https://a.com", "https://b.com"]


def test_cors_single_origin(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://only.com")
    assert config.load_config()["CORS_ALLOW_ORIGINS"] == ["https://only.com"]


def test_cors_drops_empty_entries(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.com,,")
    assert config.load_config()["CORS_ALLOW_ORIGINS"] == ["https://a.com"]
