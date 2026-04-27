"""Entry point.

Production: gunicorn imports `app` from this module (`gunicorn app:app ...`).
Local dev: `python app.py` runs Flask's built-in dev server.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from flask import Flask, jsonify

import database as db
from coach import generate_coach_response
from routes import bp


app = Flask(__name__)
app.secret_key = os.environ.get("COACH_SECRET", "dev-only-change-me")
app.register_blueprint(bp)


@app.route("/health")
def health():
    """Liveness probe for the hosting platform."""
    return jsonify(status="ok", service="accountability-coach")


# (days_ago, mood, cumulative_progress, note)
_SAM_CHECKINS = [
    (8, "happy",       10, "First long run. Felt strong."),
    (5, "neutral",     18, "Got it done. Legs heavy."),
    (3, "frustrated",  24, "Knee tightness slowed me down."),
    (1, "neutral",     32, "Back on track. Easy pace."),
    (0, "happy",       40, "Quick recovery jog. Feeling it."),
]

_MAYA_CHECKINS = [
    (10, "happy",       3000, "Opening chapter draft is on the page."),
    ( 7, "neutral",     7500, "Slogging through the middle."),
    ( 4, "frustrated",  9000, "Deleted a scene I'd liked. Hurt."),
    ( 2, "anxious",    12000, "Catching up after losing a few days."),
    ( 0, "neutral",    14000, "Back to a steady cadence."),
]


def _seed_demo_data() -> None:
    """Insert two demo goals + 5 check-ins each so the live demo isn't empty.

    No-op if any goals already exist.
    """
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM goals LIMIT 1").fetchone():
            return

    today = date.today()

    def _ts(days_ago: int, hour: int = 9) -> str:
        dt = datetime.combine(today - timedelta(days=days_ago), datetime.min.time())
        return dt.replace(hour=hour).isoformat()

    seeds = [
        {
            "name": "Sam",
            "title": "Run 50km this month",
            "description": "Build base mileage for the half marathon in May.",
            "target_value": 50,
            "target_date": (today + timedelta(days=14)).isoformat(),
            "created_at": _ts(14),
            "checkins": _SAM_CHECKINS,
        },
        {
            "name": "Maya",
            "title": "Write 50,000 words of the novel draft",
            "description": "First-draft sprint -- aim for messy, not perfect.",
            "target_value": 50000,
            "target_date": (today + timedelta(days=30)).isoformat(),
            "created_at": _ts(14),
            "checkins": _MAYA_CHECKINS,
        },
    ]

    for g in seeds:
        goal_id = db.create_goal(
            name=g["name"],
            title=g["title"],
            description=g["description"],
            target_date=g["target_date"],
            target_value=g["target_value"],
        )
        # Backdate created_at so the pace math reflects the seeded arc.
        with db.connect() as conn:
            conn.execute(
                "UPDATE goals SET created_at = ? WHERE id = ?",
                (g["created_at"], goal_id),
            )

        prior_dates: list[str] = []
        prev_value: int | None = None
        last_at: str | None = None
        for days_ago, mood, prog, note in sorted(g["checkins"], key=lambda x: -x[0]):
            ts = _ts(days_ago)
            r = generate_coach_response(
                name=g["name"],
                title=g["title"],
                current_value=prog,
                target_value=g["target_value"],
                created_at=g["created_at"],
                target_date=g["target_date"],
                mood=mood,
                today=today - timedelta(days=days_ago),
                previous_value=prev_value,
                last_checkin_at=last_at,
                prior_checkin_dates=list(prior_dates),
            )
            with db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO check_ins (
                        goal_id, mood, progress_value, note,
                        coach_message, coach_tone, coach_action,
                        coach_assessment, coach_next_days, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (goal_id, mood, prog, note,
                     r["message"], r["tone"], r["action_item"],
                     r["progress_assessment"], r["days_until_next_checkin"], ts),
                )
            prior_dates.append(ts)
            prev_value = prog
            last_at = ts

        final_value = sorted(g["checkins"], key=lambda x: -x[0])[-1][2]
        db.update_goal_progress(goal_id, final_value)


# Run at import time so gunicorn workers boot with a ready, populated DB.
db.init_db()
_seed_demo_data()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
