"""Flask routes. Thin layer: validate -> persist -> render."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

import database as db
from coach import generate_coach_response
from validation import ValidationError, validate_check_in, validate_goal

bp = Blueprint("coach", __name__)

# How many days the streak calendar covers; 7 cols x 4 rows reads as a month.
STREAK_GRID_DAYS = 28
# Cap on the mood timeline so dense histories don't crush dot spacing.
MOOD_TIMELINE_MAX = 14

# Quote pools per overall-pace band. Rotate deterministically by date so the
# banner doesn't re-shuffle on every page reload but does change day to day.
MOTIVATION_QUOTES = {
    "behind": [
        "Restart small. The next move doesn't have to be impressive -- it has to be real.",
        "Falling behind isn't failing. Quitting is failing.",
        "What's the smallest possible version of the next step?",
        "The best time to start was last week. The second-best time is right now.",
    ],
    "on_track": [
        "The boring middle is where most goals are won. You're in it.",
        "Consistency beats intensity. You're proving it.",
        "Today's check-in is tomorrow's momentum.",
        "Steady is the whole game. Keep showing up.",
    ],
    "ahead": [
        "You're not just on pace -- you're ahead. Don't waste this window.",
        "Momentum is rare. Protect it.",
        "The streak you're building now is the story you'll tell later.",
        "Ahead of pace is a privilege of doing the work. Keep going.",
    ],
}
# Tighter +/- 10pt threshold than the per-goal assessment uses; the dashboard
# banner is a vibe read across all goals, so don't treat one slipping goal as
# a rallying cry.
MOTIVATION_BAND_THRESHOLD = 10


def _progress_pct(current: int, target: int) -> int:
    if target <= 0:
        return 0
    return min(100, int((current / target) * 100))


def _days_left(target_date: str) -> int:
    return (date.fromisoformat(target_date) - date.today()).days


def _progress_band(pct: int) -> str:
    if pct < 25:
        return "red"
    if pct < 50:
        return "orange"
    if pct < 75:
        return "yellow"
    return "green"


def _checkin_dates(rows) -> set[date]:
    """Set of unique YYYY-MM-DD dates that had at least one check-in."""
    out: set[date] = set()
    for r in rows:
        try:
            out.add(datetime.fromisoformat(r["created_at"]).date())
        except (ValueError, TypeError, KeyError):
            continue
    return out


def _streak_grid(checkin_dates: set[date], today: date, days: int = STREAK_GRID_DAYS):
    """Oldest-first list of {date, active} for the rolling window ending today.

    Oldest-first matches normal left-to-right reading; today lands in the
    bottom-right of a 7-col grid.
    """
    return [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "active": (today - timedelta(days=offset)) in checkin_dates,
        }
        for offset in range(days - 1, -1, -1)
    ]


def _current_streak(checkin_dates: set[date], today: date) -> int:
    """Consecutive days ending at the most recent check-in (today or yesterday).

    If neither today nor yesterday has a check-in, the streak is 0 -- the run
    ended too long ago to still count as "current."
    """
    if today in checkin_dates:
        cursor = today
    elif (today - timedelta(days=1)) in checkin_dates:
        cursor = today - timedelta(days=1)
    else:
        return 0
    streak = 0
    while cursor in checkin_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _mood_timeline(rows, max_points: int = MOOD_TIMELINE_MAX):
    """Most recent N check-ins, returned chronologically (oldest -> newest).

    Input rows are DESC by created_at (per database.list_check_ins), so we
    take the first N then reverse.
    """
    out = []
    for r in rows[:max_points]:
        try:
            d = datetime.fromisoformat(r["created_at"]).date().isoformat()
        except (ValueError, TypeError, KeyError):
            continue
        out.append({"date": d, "mood": r["mood"]})
    out.reverse()
    return out


def _milestones(pct: int):
    return [{"pct": p, "unlocked": pct >= p} for p in (25, 50, 75, 100)]


def _last_checkin_label(rows, today: date) -> str:
    """Human-readable 'when did they last check in' for the dashboard."""
    if not rows:
        return "no check-ins yet"
    try:
        last = datetime.fromisoformat(rows[0]["created_at"]).date()
    except (ValueError, TypeError, KeyError):
        return "unknown"
    days = (today - last).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _expected_pct(created_at: str, target_date: str, today: date) -> float:
    """Mirror of coach._expected_progress_pct -- duplicated to keep routes
    independent of the coach module's internal helpers."""
    try:
        start = datetime.fromisoformat(created_at).date()
        end = date.fromisoformat(target_date)
    except (ValueError, TypeError):
        return 0.0
    total_days = max((end - start).days, 1)
    elapsed = (today - start).days
    return max(0.0, min(100.0, (elapsed / total_days) * 100))


def _motivation_for(enriched_goals: list[dict], today: date) -> dict | None:
    """Pick one quote based on average pace across all goals.

    Returns None when there's nothing to motivate (no goals).
    """
    if not enriched_goals:
        return None
    deltas = []
    for g in enriched_goals:
        ep = _expected_pct(g["created_at"], g["target_date"], today)
        deltas.append(g["progress_pct"] - ep)
    avg = sum(deltas) / len(deltas)
    if avg >= MOTIVATION_BAND_THRESHOLD:
        band = "ahead"
    elif avg <= -MOTIVATION_BAND_THRESHOLD:
        band = "behind"
    else:
        band = "on_track"
    pool = MOTIVATION_QUOTES[band]
    return {"band": band, "text": pool[today.toordinal() % len(pool)]}


@bp.route("/")
def home():
    return render_template("home.html")


@bp.route("/goals/new", methods=["GET"])
def new_goal_form():
    return render_template(
        "new_goal.html",
        form={},
        today=date.today().isoformat(),
    )


@bp.route("/goals", methods=["POST"])
def create_goal():
    try:
        goal = validate_goal(request.form)
    except ValidationError as e:
        flash(str(e), "error")
        return (
            render_template(
                "new_goal.html",
                form=request.form,
                today=date.today().isoformat(),
            ),
            400,
        )

    db.create_goal(
        name=goal.name,
        title=goal.title,
        description=goal.description,
        target_date=goal.target_date,
        target_value=goal.target_value,
    )
    flash(f"Goal '{goal.title}' set. Let's go.", "success")
    return redirect(url_for("coach.dashboard", name=goal.name))


# Display order for moods in the form — keep this stable for users.
MOOD_ORDER = ("happy", "neutral", "frustrated", "anxious")


@bp.route("/dashboard")
def dashboard():
    name = (request.args.get("name") or "").strip() or None
    goals = db.list_goals(name=name)
    today = date.today()
    enriched = []
    for g in goals:
        all_checkins = db.list_check_ins(g["id"])
        dates = _checkin_dates(all_checkins)
        pct = _progress_pct(g["current_value"], g["target_value"])
        enriched.append({
            **dict(g),
            "progress_pct": pct,
            "progress_band": _progress_band(pct),
            "days_left": _days_left(g["target_date"]),
            "recent_check_ins": db.list_recent_check_ins(g["id"], limit=3),
            "current_streak": _current_streak(dates, today),
            "streak_grid": _streak_grid(dates, today),
            "mood_timeline": _mood_timeline(all_checkins),
            "milestones": _milestones(pct),
            "last_checkin_label": _last_checkin_label(all_checkins, today),
        })
    motivation = _motivation_for(enriched, today)
    return render_template(
        "dashboard.html",
        goals=enriched,
        name_filter=name,
        motivation=motivation,
    )


@bp.route("/goals/<int:goal_id>/checkin", methods=["GET"])
def checkin_form(goal_id: int):
    goal = db.get_goal(goal_id)
    if goal is None:
        abort(404)
    return render_template(
        "checkin.html",
        goal=goal,
        moods=MOOD_ORDER,
        form={},
    )


@bp.route("/goals/<int:goal_id>/checkin", methods=["POST"])
def submit_checkin(goal_id: int):
    goal = db.get_goal(goal_id)
    if goal is None:
        abort(404)

    form = request.form.to_dict()
    form["goal_id"] = str(goal_id)

    try:
        check_in = validate_check_in(form, max_progress=goal["target_value"])
    except ValidationError as e:
        flash(str(e), "error")
        return (
            render_template(
                "checkin.html",
                goal=goal,
                moods=MOOD_ORDER,
                form=form,
            ),
            400,
        )

    # Read prior check-ins BEFORE saving the new one. We need:
    #   - the most recent one for trend / silence / milestone signals
    #   - the full list of dates for streak detection
    prior_rows = db.list_check_ins(goal_id)
    prior_row = prior_rows[0] if prior_rows else None
    prior_dates = [r["created_at"] for r in prior_rows]

    db.update_goal_progress(goal_id, check_in.progress_value)

    coach = generate_coach_response(
        name=goal["name"],
        title=goal["title"],
        current_value=check_in.progress_value,
        target_value=goal["target_value"],
        created_at=goal["created_at"],
        target_date=goal["target_date"],
        mood=check_in.mood,
        previous_value=prior_row["progress_value"] if prior_row else None,
        last_checkin_at=prior_row["created_at"] if prior_row else None,
        prior_checkin_dates=prior_dates,
    )

    db.create_check_in(
        goal_id=goal_id,
        mood=check_in.mood,
        progress_value=check_in.progress_value,
        note=check_in.note,
        coach_message=coach["message"],
        coach_tone=coach["tone"],
        coach_action=coach["action_item"],
        coach_assessment=coach["progress_assessment"],
        coach_next_days=coach["days_until_next_checkin"],
    )

    flash(f"Check-in saved. {coach['message']}", "success")
    return redirect(url_for("coach.dashboard"))
