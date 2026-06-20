"""Tests for the service-layer orchestration in services.py.

These exercise the real persistence layer (isolated temp DB) and mock only the
external boundaries: the Manfred HTTP client and the Discord notifier.
"""
import discord_notifier
import manfred_api
import services


def _offer(offer_id, **overrides):
    base = {
        "id": offer_id,
        "position": "Backend Engineer",
        "company": {"name": "ACME", "logoDark": {"url": "http://logo/x.png"}},
        "remotePercentage": 100,
        "salaryFrom": 40000,
        "salaryTo": 60000,
        "locations": ["Madrid"],
        "slug": f"backend-{offer_id}",
    }
    base.update(overrides)
    return base


# Job-details payload shaped like the Manfred detail endpoint.
DETAILS_WITH_SKILLS = {
    "skillsSectionData": {
        "skills": {
            "must": [{"skill": "Python", "level": 3}],
            "nice": [],
            "extra": [],
        },
        "minLanguages": [{"name": "English", "level": "C1"}],
    }
}


# --- fetch_and_store_offers_service ----------------------------------------

def test_fetch_and_store_returns_error_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(manfred_api, "fetch_raw_offers_list", lambda: None)
    result = services.fetch_and_store_offers_service()
    assert result["status"] == "error"
    assert "Failed to fetch data" in result["message"]


def test_fetch_and_store_returns_error_on_non_list_payload(monkeypatch):
    monkeypatch.setattr(manfred_api, "fetch_raw_offers_list", lambda: {"not": "a list"})
    result = services.fetch_and_store_offers_service()
    assert result["status"] == "error"
    assert "Invalid response format" in result["message"]


def test_fetch_and_store_happy_path_stores_processes_and_notifies(monkeypatch):
    monkeypatch.setattr(manfred_api, "fetch_raw_offers_list", lambda: [_offer(1), _offer(2)])
    monkeypatch.setattr(manfred_api, "fetch_job_details_data",
                        lambda offer_id, slug: DETAILS_WITH_SKILLS)
    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "http://webhook")

    sent = []
    monkeypatch.setattr(discord_notifier, "send_batch_notifications",
                        lambda offers, *a, **k: (sent.extend(offers), len(offers))[1])

    result = services.fetch_and_store_offers_service()

    assert result["status"] == "success"
    assert result["total_fetched"] == 2
    assert result["new_offers"] == 2
    assert result["updated_offers"] == 0
    assert result["skills_processed"] == 2
    assert result["webhook_sent"] == 2
    # Both offers were notified and marked as sent in the DB.
    assert {o["id"] for o in sent} == {1, 2}
    import database
    assert database.get_pending_notification_offers() == []


def test_fetch_and_store_skips_notifications_without_webhook(monkeypatch):
    monkeypatch.setattr(manfred_api, "fetch_raw_offers_list", lambda: [_offer(1)])
    monkeypatch.setattr(manfred_api, "fetch_job_details_data",
                        lambda offer_id, slug: DETAILS_WITH_SKILLS)
    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "")

    def fail(*a, **k):
        raise AssertionError("send_batch_notifications must not be called without a webhook")

    monkeypatch.setattr(discord_notifier, "send_batch_notifications", fail)

    result = services.fetch_and_store_offers_service()
    assert result["webhook_sent"] == 0
    assert result["new_offers"] == 1


# --- process_pending_details_service ---------------------------------------

def test_process_pending_details_stores_skills_and_languages(monkeypatch):
    import database
    database.store_or_update_offers([_offer(1)])
    monkeypatch.setattr(manfred_api, "fetch_job_details_data",
                        lambda offer_id, slug: DETAILS_WITH_SKILLS)

    processed = services.process_pending_details_service(limit=10)

    assert processed == 1
    assert database.get_offer_by_id(1)["skills_retrieved"] is True
    skills = database.get_job_skills_from_db(1)
    assert [s["skill"] for s in skills["must"]] == ["Python"]
    assert database.get_job_languages_from_db(1) == [{"name": "English", "level": "C1"}]


def test_process_pending_details_none_when_no_pending(monkeypatch):
    assert services.process_pending_details_service(limit=10) == 0


# --- send_pending_notifications_service ------------------------------------

def test_send_pending_notifications_without_webhook(monkeypatch):
    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "")
    assert services.send_pending_notifications_service(limit=5) == (0, 0)


def test_send_pending_notifications_sends_and_marks(monkeypatch):
    import database
    database.store_or_update_offers([_offer(1), _offer(2)])
    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "http://webhook")
    monkeypatch.setattr(discord_notifier, "send_batch_notifications",
                        lambda offers, *a, **k: len(offers))

    sent, remaining = services.send_pending_notifications_service(limit=5)

    assert sent == 2
    assert remaining == 0
    assert database.get_pending_notification_offers() == []


def test_send_pending_notifications_none_when_empty(monkeypatch):
    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "http://webhook")
    assert services.send_pending_notifications_service(limit=5) == (0, 0)


# --- get_job_skills_service ------------------------------------------------

def test_get_job_skills_service_unknown_offer_returns_none():
    assert services.get_job_skills_service(424242) is None


def test_get_job_skills_service_returns_skills_and_languages():
    import database
    database.store_or_update_offers([_offer(1)])
    database.store_job_skills(1, {"must": [{"skill": "Go", "level": 1}], "nice": [], "extra": []})
    database.store_job_languages(1, [{"name": "Spanish", "level": "C2"}])

    result = services.get_job_skills_service(1)
    assert [s["skill"] for s in result["skills"]["must"]] == ["Go"]
    assert result["languages"] == [{"name": "Spanish", "level": "C2"}]


# --- get_health_status_service ---------------------------------------------

def test_health_status_reports_healthy_when_db_connected():
    status_data, is_healthy = services.get_health_status_service()
    assert is_healthy is True
    assert status_data["status"] == "healthy"
    assert status_data["database_status"] == "connected"


# --- cleanup_obsolete_job_notifications_service ----------------------------

def test_cleanup_without_webhook_returns_zero(monkeypatch):
    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "")
    assert services.cleanup_obsolete_job_notifications_service() == 0


def test_cleanup_deletes_obsolete_messages(monkeypatch):
    import database
    database.store_or_update_offers([_offer(1), _offer(2)])
    database.update_discord_message_id(1, "msg-1")
    database.update_discord_message_id(2, "msg-2")

    monkeypatch.setitem(services.CONFIG, "DISCORD_WEBHOOK_URL", "http://webhook")
    # Only offer 2 is still active -> offer 1 is obsolete.
    monkeypatch.setattr(manfred_api, "fetch_raw_offers_list", lambda: [_offer(2)])
    deleted_ids = []
    monkeypatch.setattr(discord_notifier, "delete_discord_message",
                        lambda mid: (deleted_ids.append(mid), True)[1])

    deleted = services.cleanup_obsolete_job_notifications_service()

    assert deleted == 1
    assert deleted_ids == ["msg-1"]
    # Offer 1's message id was cleared, so it is no longer obsolete.
    assert database.get_obsolete_discord_notifications([2]) == []
