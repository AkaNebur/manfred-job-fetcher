"""Tests for the Manfred HTTP client: retry/backoff logic and response parsing.

All network access is mocked; ``time.sleep`` is patched so the backoff schedule is
asserted without real delays.
"""
import json

import httpx
import pytest

import manfred_api


# --- Test doubles ----------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", content=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.content = content if content is not None else (text.encode() or b"x")

    def json(self):
        if self._json is None:
            raise json.JSONDecodeError("no json", "", 0)
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "http://test/x"),
                response=self,
            )


class FakeClient:
    """Returns/raises queued items in order, recording each call."""

    def __init__(self, items):
        self._items = list(items)
        self.calls = []

    def _next(self, method, url):
        self.calls.append((method, url))
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        return self._next("GET", url)

    def post(self, url, **kwargs):
        return self._next("POST", url)


@pytest.fixture
def patch_client(monkeypatch):
    """Install a FakeClient and capture backoff sleep durations."""
    sleeps = []
    monkeypatch.setattr(manfred_api.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setitem(manfred_api.CONFIG, "MAX_RETRIES", 3)
    monkeypatch.setitem(manfred_api.CONFIG, "RETRY_BACKOFF", 0.5)

    def install(items):
        client = FakeClient(items)
        monkeypatch.setattr(manfred_api, "http_client", client)
        return client, sleeps

    return install


# --- make_api_request: retry / backoff -------------------------------------

def test_success_on_first_try_does_not_retry(patch_client):
    client, sleeps = patch_client([FakeResponse(200)])
    resp = manfred_api.make_api_request("http://test/ok")
    assert resp.status_code == 200
    assert len(client.calls) == 1
    assert sleeps == []


def test_retries_on_5xx_then_succeeds(patch_client):
    client, sleeps = patch_client([FakeResponse(503), FakeResponse(503), FakeResponse(200)])
    resp = manfred_api.make_api_request("http://test/flaky")
    assert resp.status_code == 200
    assert len(client.calls) == 3
    # backoff_factor * 2**retries -> 0.5*2, 0.5*4
    assert sleeps == [1.0, 2.0]


def test_exhausts_retries_on_persistent_5xx_returns_none(patch_client):
    client, sleeps = patch_client([FakeResponse(500)] * 4)
    # MAX_RETRIES defaults to 3 in the fixture -> 4 attempts total.
    resp = manfred_api.make_api_request("http://test/down")
    assert resp is None
    assert len(client.calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_client_error_4xx_is_not_retried(patch_client):
    client, sleeps = patch_client([FakeResponse(404)])
    resp = manfred_api.make_api_request("http://test/missing")
    assert resp is None
    assert len(client.calls) == 1
    assert sleeps == []


def test_timeout_is_retried_then_gives_up(patch_client):
    client, sleeps = patch_client([httpx.TimeoutException("t")] * 4)
    resp = manfred_api.make_api_request("http://test/slow")
    assert resp is None
    assert len(client.calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_post_method_is_used_when_requested(patch_client):
    client, _ = patch_client([FakeResponse(200)])
    manfred_api.make_api_request("http://test/post", method="POST", json_payload={"a": 1})
    assert client.calls == [("POST", "http://test/post")]


# --- fetch_raw_offers_list -------------------------------------------------

def test_fetch_raw_offers_returns_parsed_json(monkeypatch):
    monkeypatch.setattr(manfred_api, "make_api_request",
                        lambda url: FakeResponse(json_data=[{"id": 1}]))
    assert manfred_api.fetch_raw_offers_list() == [{"id": 1}]


def test_fetch_raw_offers_returns_none_on_failed_request(monkeypatch):
    monkeypatch.setattr(manfred_api, "make_api_request", lambda url: None)
    assert manfred_api.fetch_raw_offers_list() is None


def test_fetch_raw_offers_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(manfred_api, "make_api_request", lambda url: FakeResponse(json_data=None))
    assert manfred_api.fetch_raw_offers_list() is None


# --- fetch_job_details_data ------------------------------------------------

def test_fetch_job_details_missing_slug_returns_none_without_request(monkeypatch):
    called = []
    monkeypatch.setattr(manfred_api, "make_api_request", lambda *a, **k: called.append(1))
    assert manfred_api.fetch_job_details_data(1, "") is None
    assert called == []


def test_fetch_job_details_happy_path_builds_url_and_extracts_offer(monkeypatch):
    monkeypatch.setitem(manfred_api.CONFIG, "BUILD_ID_HASH", "hash123")
    captured = {}

    def fake_make(url, *a, **k):
        captured["url"] = url
        return FakeResponse(json_data={"pageProps": {"offer": {"id": 7, "position": "Dev"}}})

    monkeypatch.setattr(manfred_api, "make_api_request", fake_make)

    result = manfred_api.fetch_job_details_data(7, "dev-role")
    assert result == {"id": 7, "position": "Dev"}
    assert "hash123" in captured["url"]
    assert "/7/" in captured["url"]
    assert "dev-role" in captured["url"]


def test_fetch_job_details_structure_mismatch_returns_none(monkeypatch):
    monkeypatch.setitem(manfred_api.CONFIG, "BUILD_ID_HASH", "hash123")
    monkeypatch.setattr(manfred_api, "make_api_request",
                        lambda url: FakeResponse(json_data={"pageProps": {}}))
    # retry_on_hash_error=False to avoid the hash-refresh recursion path.
    assert manfred_api.fetch_job_details_data(7, "dev-role", retry_on_hash_error=False) is None


# --- fetch_and_update_build_id_hash (regex extraction) ---------------------

def test_build_hash_extracted_from_html_and_updated(monkeypatch):
    monkeypatch.setitem(manfred_api.CONFIG, "BUILD_ID_HASH", "old")
    monkeypatch.setenv("BUILD_ID_HASH", "old")
    monkeypatch.setattr(manfred_api, "save_build_hash_to_file", lambda h: True)
    monkeypatch.setattr(manfred_api, "make_api_request",
                        lambda url: FakeResponse(text='window={"buildId":"ABC123","x":1}'))

    assert manfred_api.fetch_and_update_build_id_hash() is True
    assert manfred_api.CONFIG["BUILD_ID_HASH"] == "ABC123"


def test_build_hash_no_match_returns_false_and_keeps_current(monkeypatch):
    monkeypatch.setitem(manfred_api.CONFIG, "BUILD_ID_HASH", "old")
    monkeypatch.setattr(manfred_api, "make_api_request",
                        lambda url: FakeResponse(text="no build id present here"))

    assert manfred_api.fetch_and_update_build_id_hash() is False
    assert manfred_api.CONFIG["BUILD_ID_HASH"] == "old"


def test_build_hash_returns_false_when_page_fetch_fails(monkeypatch):
    monkeypatch.setattr(manfred_api, "make_api_request", lambda url: None)
    assert manfred_api.fetch_and_update_build_id_hash() is False
