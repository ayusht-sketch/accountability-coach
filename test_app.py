"""End-to-end test suite for the Accountability Coach.

Run: python test_app.py
Exit code 0 = all pass, 1 = any failures.

Five categories:
  1. Database persistence + streak math
  2. Input validation (rejection + tag scrubbing)
  3. AI coaching tones for the four canonical scenarios
  4. Edge cases (overflow, zero, due-today, long note, multi-goal)
  5. Flask routes via the test client (incl. /health)

Each test runs against a fresh temp SQLite DB. The Flask app is imported
once -- but its DB_PATH is patched to the temp file BEFORE import, so the
import-time init_db() + seed land in the throwaway DB instead of coach.db.
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

# --- Isolate DB before importing anything that touches it ------------------
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
_TEST_DB = Path(_tmp.name)

import database as db
db.DB_PATH = _TEST_DB

from validation import ValidationError, validate_check_in, validate_goal  # noqa: E402
from coach import VALID_TONES, generate_coach_response  # noqa: E402
from routes import _current_streak  # noqa: E402

import app as app_module  # noqa: E402  -- triggers init_db() + seed into _TEST_DB
flask_app = app_module.app

TODAY = date.today()


# --- Harness ---------------------------------------------------------------
RESULTS: list[tuple[str, str, str, str | None]] = []
_current_category = ""


def reset_db() -> None:
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    db.init_db()


def section(label: str) -> None:
    global _current_category
    _current_category = label
    print(f"\n--- {label} ---")


def run(name: str, fn) -> None:
    try:
        reset_db()
        fn()
        RESULTS.append((_current_category, name, "PASS", None))
        print(f"  PASS   {name}")
    except AssertionError as e:
        tb = traceback.format_exc()
        RESULTS.append((_current_category, name, "FAIL", tb))
        print(f"  FAIL   {name}: {e}")
    except Exception as e:
        tb = traceback.format_exc()
        RESULTS.append((_current_category, name, "ERROR", tb))
        print(f"  ERROR  {name}: {e}")


def _expect_validation_error(callable_, *, contains: str = "") -> None:
    try:
        callable_()
    except ValidationError as e:
        if contains and contains.lower() not in str(e).lower():
            raise AssertionError(f"wrong error message: {e!r}")
        return
    raise AssertionError("expected ValidationError, none raised")


# === 1. DATABASE ===========================================================

def t_create_and_read_goal():
    gid = db.create_goal(
        name="Sam", title="Run 50km", description="base mileage",
        target_date=(TODAY + timedelta(days=30)).isoformat(), target_value=50,
    )
    assert isinstance(gid, int) and gid > 0
    row = db.get_goal(gid)
    assert row is not None
    assert row["name"] == "Sam"
    assert row["title"] == "Run 50km"
    assert row["description"] == "base mileage"
    assert row["target_value"] == 50
    assert row["current_value"] == 0
    assert row["target_date"] == (TODAY + timedelta(days=30)).isoformat()


def t_checkin_persists_with_coaching():
    gid = db.create_goal(
        "Sam", "Run 50km", "",
        (TODAY + timedelta(days=30)).isoformat(), 50,
    )
    db.create_check_in(
        goal_id=gid, mood="happy", progress_value=10, note="strong run",
        coach_message="Nice work!", coach_tone="celebration",
        coach_action="keep going", coach_assessment="On pace.",
        coach_next_days=7,
    )
    rows = db.list_check_ins(gid)
    assert len(rows) == 1
    r = rows[0]
    assert r["mood"] == "happy"
    assert r["progress_value"] == 10
    assert r["note"] == "strong run"
    assert r["coach_message"] == "Nice work!"
    assert r["coach_tone"] == "celebration"
    assert r["coach_action"] == "keep going"
    assert r["coach_assessment"] == "On pace."
    assert r["coach_next_days"] == 7


def t_list_goals_shape():
    db.create_goal("Sam", "Goal A", "", (TODAY + timedelta(days=10)).isoformat(), 100)
    db.create_goal("Maya", "Goal B", "", (TODAY + timedelta(days=10)).isoformat(), 200)
    rows = db.list_goals()
    assert len(rows) == 2
    expected = {"id", "name", "title", "description", "target_date",
                "target_value", "current_value", "created_at"}
    for r in rows:
        assert set(r.keys()) == expected, f"unexpected keys: {set(r.keys())}"
    sams = db.list_goals(name="Sam")
    assert len(sams) == 1 and sams[0]["name"] == "Sam"


def t_streak_today_only():
    assert _current_streak({TODAY}, TODAY) == 1


def t_streak_four_consecutive():
    dates = {TODAY - timedelta(days=i) for i in range(4)}
    assert _current_streak(dates, TODAY) == 4


def t_streak_yesterday_anchored():
    # No today, but yesterday + day-before -> streak of 2 ending yesterday.
    dates = {TODAY - timedelta(days=1), TODAY - timedelta(days=2)}
    assert _current_streak(dates, TODAY) == 2


def t_streak_stale_is_zero():
    # Last activity 3+ days ago -> the run is over.
    dates = {TODAY - timedelta(days=3), TODAY - timedelta(days=4)}
    assert _current_streak(dates, TODAY) == 0


# === 2. VALIDATION =========================================================

VALID_FUTURE = (TODAY + timedelta(days=14)).isoformat()


def t_val_empty_title_rejected():
    _expect_validation_error(
        lambda: validate_goal({
            "name": "Sam", "title": "   ",
            "target_date": VALID_FUTURE, "target_value": "10",
        }),
        contains="title",
    )


def t_val_past_target_date_rejected():
    past = (TODAY - timedelta(days=1)).isoformat()
    _expect_validation_error(
        lambda: validate_goal({
            "name": "Sam", "title": "Goal",
            "target_date": past, "target_value": "10",
        }),
        contains="past",
    )


def t_val_negative_progress_rejected():
    _expect_validation_error(
        lambda: validate_check_in(
            {"goal_id": "1", "mood": "happy", "progress_value": "-5"},
            max_progress=100,
        ),
        contains="negative",
    )


def t_val_unknown_mood_rejected():
    _expect_validation_error(
        lambda: validate_check_in(
            {"goal_id": "1", "mood": "ecstatic", "progress_value": "5"},
            max_progress=100,
        ),
        contains="mood",
    )


def t_val_script_tag_in_title_rejected():
    _expect_validation_error(
        lambda: validate_goal({
            "name": "Sam",
            "title": "Run 5km <script>alert(1)</script>",
            "target_date": VALID_FUTURE, "target_value": "10",
        }),
        contains="html",
    )


def t_val_script_tag_in_note_rejected():
    _expect_validation_error(
        lambda: validate_check_in(
            {"goal_id": "1", "mood": "happy", "progress_value": "5",
             "note": "Did 5km <script>steal()</script>"},
            max_progress=100,
        ),
        contains="html",
    )


def t_val_html_in_description_rejected():
    _expect_validation_error(
        lambda: validate_goal({
            "name": "Sam", "title": "Run 5km",
            "description": "Build base <b>mileage</b>",
            "target_date": VALID_FUTURE, "target_value": "10",
        }),
        contains="html",
    )


# === 3. AI COACHING TONES ==================================================

EXPECTED_KEYS = {
    "message", "tone", "action_item", "progress_assessment",
    "days_until_next_checkin", "streak_days", "streak_callout",
}


def _assert_response_shape(r: dict) -> None:
    assert set(r.keys()) == EXPECTED_KEYS, f"keys mismatch: {set(r.keys())}"
    assert isinstance(r["message"], str) and r["message"], "empty message"
    assert r["tone"] in VALID_TONES, f"bad tone: {r['tone']}"
    assert isinstance(r["action_item"], str) and r["action_item"]
    assert isinstance(r["progress_assessment"], str) and r["progress_assessment"]
    assert isinstance(r["days_until_next_checkin"], int)
    assert r["days_until_next_checkin"] > 0


def t_tone_behind_frustrated_is_empathy():
    # 14-day goal, day 10, only 10/100 -> well behind, no prior trend, frustrated
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=10, target_value=100,
        created_at=(TODAY - timedelta(days=10)).isoformat(),
        target_date=(TODAY + timedelta(days=4)).isoformat(),
        mood="frustrated", today=TODAY,
    )
    _assert_response_shape(r)
    assert r["tone"] == "empathy", f"got {r['tone']}: {r['message']!r}"


def t_tone_on_track_neutral_is_motivational():
    # 20-day goal, day 10, 50/100 -> 50% expected vs 50% actual, neutral mood
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=50, target_value=100,
        created_at=(TODAY - timedelta(days=10)).isoformat(),
        target_date=(TODAY + timedelta(days=10)).isoformat(),
        mood="neutral", today=TODAY,
    )
    _assert_response_shape(r)
    assert r["tone"] == "motivational", f"got {r['tone']}: {r['message']!r}"


def t_tone_ahead_happy_is_celebration():
    # 30-day goal, day 5, 50/100 -> ~17% expected vs 50% actual, happy mood
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=50, target_value=100,
        created_at=(TODAY - timedelta(days=5)).isoformat(),
        target_date=(TODAY + timedelta(days=25)).isoformat(),
        mood="happy", today=TODAY,
    )
    _assert_response_shape(r)
    assert r["tone"] == "celebration", f"got {r['tone']}: {r['message']!r}"


def t_tone_silent_is_reengagement():
    # Last check-in 5 days ago -> silence path overrides mood-based dispatch
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=10, target_value=100,
        created_at=(TODAY - timedelta(days=10)).isoformat(),
        target_date=(TODAY + timedelta(days=20)).isoformat(),
        mood="neutral", today=TODAY,
        last_checkin_at=(TODAY - timedelta(days=5)).isoformat(),
    )
    _assert_response_shape(r)
    assert r["tone"] == "reengagement", f"got {r['tone']}: {r['message']!r}"


# === 4. EDGE CASES =========================================================

def t_edge_progress_beyond_target():
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=120, target_value=100,
        created_at=(TODAY - timedelta(days=5)).isoformat(),
        target_date=(TODAY + timedelta(days=5)).isoformat(),
        mood="happy", today=TODAY,
    )
    _assert_response_shape(r)
    assert r["tone"] == "celebration"
    assert r["progress_assessment"] == "Goal complete."


def t_edge_zero_progress():
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=0, target_value=100,
        created_at=(TODAY - timedelta(days=2)).isoformat(),
        target_date=(TODAY + timedelta(days=10)).isoformat(),
        mood="neutral", today=TODAY,
    )
    _assert_response_shape(r)


def t_edge_goal_due_today():
    # days_left == 0 used to be a divide-by-zero hazard -- prove it isn't.
    r = generate_coach_response(
        name="Sam", title="Goal",
        current_value=50, target_value=100,
        created_at=(TODAY - timedelta(days=10)).isoformat(),
        target_date=TODAY.isoformat(),
        mood="neutral", today=TODAY,
    )
    _assert_response_shape(r)


def t_edge_long_note_at_cap_accepted():
    note_500 = "x" * 500
    ci = validate_check_in(
        {"goal_id": "1", "mood": "happy", "progress_value": "5", "note": note_500},
        max_progress=100,
    )
    assert len(ci.note) == 500


def t_edge_long_note_over_cap_rejected():
    _expect_validation_error(
        lambda: validate_check_in(
            {"goal_id": "1", "mood": "happy", "progress_value": "5",
             "note": "x" * 501},
            max_progress=100,
        ),
        contains="500",
    )


def t_edge_one_user_multiple_goals():
    db.create_goal("Sam", "Goal A", "", (TODAY + timedelta(days=10)).isoformat(), 50)
    db.create_goal("Sam", "Goal B", "", (TODAY + timedelta(days=20)).isoformat(), 100)
    db.create_goal("Maya", "Goal C", "", (TODAY + timedelta(days=10)).isoformat(), 30)
    sam_goals = db.list_goals(name="Sam")
    assert len(sam_goals) == 2
    assert {g["title"] for g in sam_goals} == {"Goal A", "Goal B"}


# === 5. FLASK ROUTES =======================================================

def _client():
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def t_route_home_ok():
    r = _client().get("/")
    assert r.status_code == 200, r.status_code


def t_route_dashboard_empty_ok():
    r = _client().get("/dashboard")
    assert r.status_code == 200, r.status_code


def t_route_dashboard_with_goal_ok():
    db.create_goal("Sam", "Test Goal", "",
                   (TODAY + timedelta(days=10)).isoformat(), 50)
    r = _client().get("/dashboard")
    assert r.status_code == 200, r.status_code


def t_route_health_ok():
    r = _client().get("/health")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body and body.get("status") == "ok", f"body: {body}"


def t_route_post_goals_valid_redirects_and_persists():
    r = _client().post("/goals", data={
        "name": "Sam",
        "title": "Run 5km",
        "description": "easy",
        "target_date": (TODAY + timedelta(days=30)).isoformat(),
        "target_value": "5",
    }, follow_redirects=False)
    assert r.status_code == 302, r.status_code
    assert "/dashboard" in r.headers.get("Location", "")
    rows = db.list_goals()
    assert len(rows) == 1 and rows[0]["title"] == "Run 5km"


def t_route_post_goals_invalid_returns_400_and_no_save():
    r = _client().post("/goals", data={
        "name": "Sam",
        "title": "",  # empty -> validation error
        "target_date": (TODAY + timedelta(days=30)).isoformat(),
        "target_value": "5",
    })
    assert r.status_code == 400, r.status_code
    assert len(db.list_goals()) == 0


# --- Runner ----------------------------------------------------------------

def main() -> int:
    section("1. DATABASE")
    run("create_goal + get_goal round-trip", t_create_and_read_goal)
    run("create_check_in persists coaching response", t_checkin_persists_with_coaching)
    run("list_goals returns expected row shape + filter by name", t_list_goals_shape)
    run("streak counter: today only = 1", t_streak_today_only)
    run("streak counter: 4 consecutive days = 4", t_streak_four_consecutive)
    run("streak counter: ends yesterday with no today = counts back", t_streak_yesterday_anchored)
    run("streak counter: stale (>1 day gap) = 0", t_streak_stale_is_zero)

    section("2. VALIDATION")
    run("rejects empty title", t_val_empty_title_rejected)
    run("rejects past target date", t_val_past_target_date_rejected)
    run("rejects negative progress", t_val_negative_progress_rejected)
    run("rejects unknown mood value", t_val_unknown_mood_rejected)
    run("rejects script tag in title", t_val_script_tag_in_title_rejected)
    run("rejects script tag in note", t_val_script_tag_in_note_rejected)
    run("rejects HTML tag in description", t_val_html_in_description_rejected)

    section("3. AI COACHING TONES")
    run("behind + frustrated -> empathy", t_tone_behind_frustrated_is_empathy)
    run("on-track + neutral -> motivational", t_tone_on_track_neutral_is_motivational)
    run("ahead + happy -> celebration", t_tone_ahead_happy_is_celebration)
    run("silent (3+ days) -> reengagement", t_tone_silent_is_reengagement)

    section("4. EDGE CASES")
    run("progress > target -> celebration + 'Goal complete.'", t_edge_progress_beyond_target)
    run("zero progress doesn't crash", t_edge_zero_progress)
    run("goal due today doesn't divide-by-zero", t_edge_goal_due_today)
    run("note at 500-char cap accepted", t_edge_long_note_at_cap_accepted)
    run("note over 500-char cap rejected", t_edge_long_note_over_cap_rejected)
    run("one user can hold multiple goals", t_edge_one_user_multiple_goals)

    section("5. FLASK ROUTES")
    run("GET /  -> 200", t_route_home_ok)
    run("GET /dashboard (empty) -> 200", t_route_dashboard_empty_ok)
    run("GET /dashboard (with goal) -> 200", t_route_dashboard_with_goal_ok)
    run("GET /health -> 200 + status:ok", t_route_health_ok)
    run("POST /goals (valid) -> 302 + persisted", t_route_post_goals_valid_redirects_and_persists)
    run("POST /goals (invalid) -> 400 + not persisted", t_route_post_goals_invalid_returns_400_and_no_save)

    # --- Summary ---
    passed = sum(1 for r in RESULTS if r[2] == "PASS")
    failed = [r for r in RESULTS if r[2] != "PASS"]
    total = len(RESULTS)

    print()
    print("=" * 64)
    print(f"SUMMARY  {passed}/{total} passed   {len(failed)} failed")
    print("=" * 64)

    by_cat: dict[str, list] = {}
    for cat, name, status, _tb in RESULTS:
        by_cat.setdefault(cat, []).append(status)
    for cat, statuses in by_cat.items():
        p = sum(1 for s in statuses if s == "PASS")
        print(f"  {cat:<24} {p}/{len(statuses)}")

    if failed:
        print("\nFAILURE DETAIL")
        print("-" * 64)
        for cat, name, status, tb in failed:
            print(f"\n[{cat}] {name}  --  {status}")
            print(tb.rstrip() if tb else "(no traceback)")

    if _TEST_DB.exists():
        _TEST_DB.unlink()

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
