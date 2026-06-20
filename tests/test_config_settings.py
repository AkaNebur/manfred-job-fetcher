"""Tests for the pydantic-settings backend of the configuration object.

Cover the behaviour gained by the migration: type coercion from env strings,
fail-fast validation, and the dict-style/runtime-mutation compatibility shims the
rest of the codebase relies on.
"""
import pytest
from pydantic import ValidationError

import config


def test_numeric_and_bool_env_values_are_coerced(monkeypatch):
    monkeypatch.setenv("MAX_RETRIES", "7")
    monkeypatch.setenv("RETRY_BACKOFF", "1.5")
    monkeypatch.setenv("RESET_DB", "true")
    cfg = config.load_config()
    assert cfg["MAX_RETRIES"] == 7
    assert cfg["RETRY_BACKOFF"] == 1.5
    assert cfg["RESET_DB"] is True


def test_invalid_int_fails_fast_at_load(monkeypatch):
    monkeypatch.setenv("MAX_RETRIES", "not-a-number")
    with pytest.raises(ValidationError):
        config.load_config()


def test_dict_and_attribute_access_are_equivalent():
    cfg = config.load_config()
    assert cfg["MAX_RETRIES"] == cfg.MAX_RETRIES
    assert "MAX_RETRIES" in cfg
    assert "DOES_NOT_EXIST" not in cfg
    assert cfg.get("DISCORD_WEBHOOK_URL") == cfg["DISCORD_WEBHOOK_URL"]
    assert cfg.get("DOES_NOT_EXIST", "fallback") == "fallback"


def test_runtime_mutation_via_item_assignment():
    cfg = config.load_config()
    cfg["BUILD_ID_HASH"] = "newhash123"
    assert cfg["BUILD_ID_HASH"] == "newhash123"
    assert cfg.BUILD_ID_HASH == "newhash123"


def test_assignment_is_validated():
    cfg = config.load_config()
    with pytest.raises(ValidationError):
        cfg["MAX_RETRIES"] = "abc"
