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
        })
    return render_template("dashboard.html", goals=enriched, name_filter=name)


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
