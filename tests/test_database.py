"""Contract tests for the persistence layer against a real (temporary) SQLite DB."""
import database


def _offer(offer_id, **overrides):
    """Build an offer dict shaped like the Manfred API payload."""
    base = {
        "id": offer_id,
        "position": "Backend Engineer",
        "company": {"name": "ACME", "logoDark": {"url": "http://logo/x.png"}},
        "remotePercentage": 100,
        "salaryFrom": 40000,
        "salaryTo": 60000,
        "locations": ["Madrid", "Remote"],
        "slug": f"backend-{offer_id}",
    }
    base.update(overrides)
    return base


SKILLS = {
    "must": [{"skill": "Python", "icon": "py", "level": 3, "desc": "core"}],
    "nice": [{"skill": "Docker", "level": 2}],
    "extra": [],
}


# --- store_or_update_offers ------------------------------------------------

def test_store_new_then_update_counts():
    new, updated, new_dicts = database.store_or_update_offers([_offer(1), _offer(2)])
    assert new == 2
    assert updated == 0
    assert {d["id"] for d in new_dicts} == {1, 2}

    # Re-running with one repeated and one fresh id: 1 update, 1 insert.
    new2, updated2, new_dicts2 = database.store_or_update_offers([_offer(1), _offer(3)])
    assert new2 == 1
    assert updated2 == 1
    assert [d["id"] for d in new_dicts2] == [3]


def test_store_skips_offer_without_id():
    new, updated, new_dicts = database.store_or_update_offers([{"position": "no id"}])
    assert (new, updated, new_dicts) == (0, 0, [])


def test_store_parses_locations_and_logo_and_defaults():
    database.store_or_update_offers([_offer(10, locations=["A", "B"])])
    row = database.get_offer_by_id(10)
    assert row["locations"] == "A, B"
    assert row["company_logo_dark_url"] == "http://logo/x.png"
    assert row["notification_sent"] is False
    assert row["skills_retrieved"] is False


def test_get_offer_by_id_missing_returns_none():
    assert database.get_offer_by_id(123456) is None


# --- skills ----------------------------------------------------------------

def test_store_and_get_skills_grouped_by_category():
    database.store_or_update_offers([_offer(1)])
    assert database.store_job_skills(1, SKILLS) is True

    got = database.get_job_skills_from_db(1)
    assert [s["skill"] for s in got["must"]] == ["Python"]
    assert got["must"][0]["level"] == 3
    assert [s["skill"] for s in got["nice"]] == ["Docker"]
    assert got["extra"] == []


def test_store_skills_none_marks_retrieved_but_returns_empty():
    database.store_or_update_offers([_offer(1)])
    assert database.store_job_skills(1, None) is True
    assert database.get_offer_by_id(1)["skills_retrieved"] is True
    assert database.get_job_skills_from_db(1) == {"must": [], "nice": [], "extra": []}


def test_store_skills_for_nonexistent_offer_returns_false():
    assert database.store_job_skills(999, SKILLS) is False


def test_store_skills_replaces_previous_set():
    database.store_or_update_offers([_offer(1)])
    database.store_job_skills(1, SKILLS)
    database.store_job_skills(1, {"must": [{"skill": "Go", "level": 1}], "nice": [], "extra": []})

    got = database.get_job_skills_from_db(1)
    assert [s["skill"] for s in got["must"]] == ["Go"]
    assert got["nice"] == []


def test_get_skills_empty_when_not_retrieved():
    database.store_or_update_offers([_offer(1)])
    # skills_retrieved is still False -> retrieval returns the empty shape.
    assert database.get_job_skills_from_db(1) == {"must": [], "nice": [], "extra": []}


# --- languages -------------------------------------------------------------

def test_store_and_get_languages():
    database.store_or_update_offers([_offer(1)])
    assert database.store_job_languages(1, [{"name": "English", "level": "C1"}]) is True
    assert database.get_job_languages_from_db(1) == [{"name": "English", "level": "C1"}]


def test_store_languages_empty_returns_false():
    database.store_or_update_offers([_offer(1)])
    assert database.store_job_languages(1, []) is False


# --- notification status ---------------------------------------------------

def test_pending_notifications_and_status_update():
    database.store_or_update_offers([_offer(1), _offer(2)])
    pending = database.get_pending_notification_offers(limit=10)
    assert {o["offer_id"] for o in pending} == {1, 2}

    assert database.update_notification_status([1]) == 1
    pending_after = database.get_pending_notification_offers(limit=10)
    assert {o["offer_id"] for o in pending_after} == {2}


# --- pending skill offers --------------------------------------------------

def test_pending_skill_offers_excludes_retrieved():
    database.store_or_update_offers([_offer(1), _offer(2)])
    database.store_job_skills(1, SKILLS)  # marks offer 1 as retrieved
    pending = database.get_pending_skill_offers(limit=10)
    assert {o["offer_id"] for o in pending} == {2}


# --- obsolete Discord notifications ----------------------------------------

def test_obsolete_discord_notifications_lifecycle():
    database.store_or_update_offers([_offer(1), _offer(2)])
    assert database.update_discord_message_id(1, "msg-1") is True
    assert database.update_discord_message_id(2, "msg-2") is True

    # Only offer 2 is still active -> offer 1's message is obsolete.
    obsolete = database.get_obsolete_discord_notifications([2])
    assert [o["offer_id"] for o in obsolete] == [1]
    assert obsolete[0]["discord_message_id"] == "msg-1"

    assert database.clear_discord_message_id(1) is True
    assert database.get_obsolete_discord_notifications([2]) == []
