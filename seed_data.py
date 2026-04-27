"""Drop realistic test data into the DB so the dashboard looks alive.

Wipes coach.db and creates two goals with 11 check-ins between them spread
across the last ~12 days. Coach responses are generated for each check-in
using the actual coach module, with rolling prior-state context, so the
dashboard's check-in panel shows real tones / messages / actions -- not
placeholders.

Designed so the dashboard exercises every visual:
  - progress bar bands: Sam ends at 80% (green), Maya at 28% (orange)
  - milestone markers: Sam unlocks 25/50/75; Maya unlocks 25
  - streak calendar: Sam has a 4-day current streak (today + 3 prior days)
  - mood timeline: mix of happy / neutral / frustrated / anxious
  - tone badges: all four tone colors appear across the recent-checkins lists
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import database as db
from coach import generate_coach_response


def _ts(today: date, days_ago: int, hour: int = 9) -> str:
    """ISO timestamp for a fixed hour on (today - days_ago). Stable ordering."""
    dt = datetime.combine(today - timedelta(days=days_ago), datetime.min.time())
    return dt.replace(hour=hour).isoformat()


# (days_ago, mood, cumulative_progress, note)
SAM_CHECKINS = [
    (11, "happy",      7,  "First long run. Felt strong."),
    ( 8, "neutral",    15, "Got it done. Legs heavy."),
    ( 5, "frustrated", 22, "Knee tightness slowed me down."),
    ( 3, "neutral",    28, "Back on track. Easy pace."),
    ( 2, "frustrated", 27, "Cut a session short. Frustrated."),
    ( 1, "frustrated", 35, "Pushed through. Kept going."),
    ( 0, "happy",      40, "Quick recovery jog. Feeling it."),
]

MAYA_CHECKINS = [
    (10, "happy",       3000,  "Opening chapter draft is on the page."),
    ( 6, "neutral",     7500,  "Slogging through the middle."),
    ( 4, "frustrated",  7000,  "Deleted a scene I'd liked. Hurt."),
    ( 1, "anxious",    14000,  "Catching up after losing a few days."),
]


def _insert_checkins(
    *, goal_id: int, name: str, title: str, target: int,
    target_date_iso: str, created_at_iso: str,
    checkins: list[tuple[int, str, int, str]], today: date,
) -> None:
    """Insert each check-in chronologically, generating a real coach response
    with the rolling prior context so trend / silence / milestone / streak
    signals fire correctly per row."""
    prior_dates: list[str] = []
    prev_value: int | None = None
    last_at: str | None = None

    # Oldest-first.
    for days_ago, mood, prog, note in sorted(checkins, key=lambda x: -x[0]):
        ts = _ts(today, days_ago)
        as_of = today - timedelta(days=days_ago)

        r = generate_coach_response(
            name=name,
            title=title,
            current_value=prog,
            target_value=target,
            created_at=created_at_iso,
            target_date=target_date_iso,
            mood=mood,
            today=as_of,
            previous_value=prev_value,
            last_checkin_at=last_at,
            prior_checkin_dates=list(prior_dates),
        )

        with db.connect() as c:
            c.execute(
                """
                INSERT INTO check_ins (
                    goal_id, mood, progress_value, note,
                    coach_message, coach_tone, coach_action,
                    coach_assessment, coach_next_days, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (goal_id, mood, prog, note,
                 r["message"], r["tone"], r["action_item"],
                 r["progress_assessment"], r["days_until_next_checkin"], ts),
            )

        prior_dates.append(ts)
        prev_value = prog
        last_at = ts

    # Update goal current_value to the final progress so the dashboard math
    # (band, milestones, days-left) lines up with the last check-in.
    final = sorted(checkins, key=lambda x: -x[0])[-1][2]
    db.update_goal_progress(goal_id, final)


def main() -> None:
    today = date.today()

    # Clean slate -- drop the whole DB so previous runs / real data don't mix in.
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    db.init_db()

    # ---- Goal 1: Sam, ahead of pace, current 4-day streak, hits 75% ----
    sam_target_date = (today + timedelta(days=14)).isoformat()
    sam_created_at = _ts(today, 14)
    sam_id = db.create_goal(
        name="Sam",
        title="Run 50km this month",
        description="Build base mileage for the half marathon in May.",
        target_date=sam_target_date,
        target_value=50,
    )
    # Backdate the goal's created_at so pace math reflects the real arc.
    with db.connect() as c:
        c.execute("UPDATE goals SET created_at = ? WHERE id = ?", (sam_created_at, sam_id))

    _insert_checkins(
        goal_id=sam_id,
        name="Sam",
        title="Run 50km this month",
        target=50,
        target_date_iso=sam_target_date,
        created_at_iso=sam_created_at,
        checkins=SAM_CHECKINS,
        today=today,
    )

    # ---- Goal 2: Maya, behind pace, broken-and-rejoined, hits 25% ----
    maya_target_date = (today + timedelta(days=30)).isoformat()
    maya_created_at = _ts(today, 14)
    maya_id = db.create_goal(
        name="Maya",
        title="Write 50,000 words of the novel draft",
        description="First-draft sprint -- aim for messy, not perfect.",
        target_date=maya_target_date,
        target_value=50000,
    )
    with db.connect() as c:
        c.execute("UPDATE goals SET created_at = ? WHERE id = ?", (maya_created_at, maya_id))

    _insert_checkins(
        goal_id=maya_id,
        name="Maya",
        title="Write 50,000 words of the novel draft",
        target=50000,
        target_date_iso=maya_target_date,
        created_at_iso=maya_created_at,
        checkins=MAYA_CHECKINS,
        today=today,
    )

    # ---- Summary ----
    total = len(SAM_CHECKINS) + len(MAYA_CHECKINS)
    print(f"Seeded {total} check-ins across 2 goals:")
    print(f"  Sam   -> 'Run 50km this month'             | "
          f"{SAM_CHECKINS[-1][2]}/50  ({len(SAM_CHECKINS)} check-ins)")
    print(f"  Maya  -> 'Write 50,000 words'              | "
          f"{MAYA_CHECKINS[-1][2]}/50000 ({len(MAYA_CHECKINS)} check-ins)")
    print()
    print("Now start the Flask app in your second terminal:")
    print("    python app.py")
    print("Then open http://localhost:5000/dashboard")


if __name__ == "__main__":
    main()
