"""Template-based accountability coach.

Same output shape as the original (so the day-26 contract test still passes):

    {
        "message": str,
        "tone": str,                # one of VALID_TONES
        "action_item": str,
        "progress_assessment": str,
        "days_until_next_checkin": int,
    }

Smarter than the original: in addition to mood + pace, it also considers
TREND (this check-in vs the previous one), DAYS-SILENT (gap since last
check-in), and MILESTONE (just crossed 25/50/75 %). These combine to pick
a more situation-appropriate response, while the tone vocabulary stays
the same four values: empathy | motivational | celebration | reengagement.

The new signals are passed through optional params so existing callers and
tests that don't supply them still work -- the coach degrades gracefully
to mood-and-pace reasoning.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TypedDict

from validation import ALLOWED_MOODS  # noqa: F401  (kept so tests can introspect)


class CoachResponse(TypedDict):
    message: str
    tone: str
    action_item: str
    progress_assessment: str
    days_until_next_checkin: int
    # Consistency signal -- always present, but streak_callout is "" when there's
    # nothing notable to say (streak too short, no broken streak to acknowledge).
    streak_days: int
    streak_callout: str


VALID_TONES = ("empathy", "motivational", "celebration", "reengagement")


# ---- pure helpers ---------------------------------------------------------

def _expected_progress_pct(created_at: str, target_date: str, today: date) -> float:
    """How far along the user *should* be, based on elapsed time."""
    start = datetime.fromisoformat(created_at).date()
    end = date.fromisoformat(target_date)
    total_days = max((end - start).days, 1)
    elapsed = (today - start).days
    pct = (elapsed / total_days) * 100
    return max(0.0, min(100.0, pct))


def _assessment(progress_pct: float, expected_pct: float) -> str:
    delta = progress_pct - expected_pct
    if progress_pct >= 100:
        return "Goal complete."
    if delta >= 10:
        return f"Ahead of pace ({progress_pct:.0f}% done vs. {expected_pct:.0f}% expected)."
    if delta >= -10:
        return f"On pace ({progress_pct:.0f}% done vs. {expected_pct:.0f}% expected)."
    if delta >= -25:
        return f"Slightly behind ({progress_pct:.0f}% done vs. {expected_pct:.0f}% expected)."
    return f"Significantly behind ({progress_pct:.0f}% done vs. {expected_pct:.0f}% expected)."


def _next_checkin_days(tone: str) -> int:
    return {"celebration": 7, "motivational": 5, "empathy": 3, "reengagement": 2}[tone]


def _trend(current: int, previous: int | None) -> str:
    """Direction of motion vs. the previous check-in. 'first' if no prior data."""
    if previous is None:
        return "first"
    if current > previous:
        return "improving"
    if current < previous:
        return "declining"
    return "stagnant"


def _days_silent(last_checkin_at: str | None, today: date) -> int:
    if not last_checkin_at:
        return 0
    last = datetime.fromisoformat(last_checkin_at).date()
    return max(0, (today - last).days)


def _compute_streaks(
    today: date, prior_checkin_dates: list[str] | None
) -> tuple[int, int]:
    """Return (current_streak, broken_streak_length).

    current_streak: consecutive days ending today, INCLUDING today's check-in.
        Always >= 1. Min value 1 means today is the only check-in in the run.
    broken_streak_length: if yesterday wasn't a check-in but there was a run of
        consecutive days before the gap, the length of that run. 0 otherwise.
        Used to spot "you had momentum, hit a gap, now you're back" moments.
    """
    if not prior_checkin_dates:
        return 1, 0

    prior_set: set[date] = set()
    for s in prior_checkin_dates:
        try:
            d = datetime.fromisoformat(s).date()
        except ValueError:
            continue
        # Don't conflate today with a prior date if today already appears.
        if d != today:
            prior_set.add(d)

    current = 1
    d = today - timedelta(days=1)
    while d in prior_set:
        current += 1
        d -= timedelta(days=1)

    broken = 0
    if (today - timedelta(days=1)) not in prior_set and prior_set:
        most_recent = max(prior_set)
        broken = 1
        d = most_recent - timedelta(days=1)
        while d in prior_set:
            broken += 1
            d -= timedelta(days=1)

    return current, broken


def _streak_callout(current: int, broken: int) -> str:
    """One-liner the dashboard can show next to the main message. Empty when
    there's nothing the user benefits from hearing."""
    # An active 3+ day run is the headline -- name it explicitly.
    if current >= 3:
        return f"{current} check-ins in a row -- that consistency is building something."
    # Only acknowledge a broken streak if it was actually a streak (>=2 days).
    # A single-day "streak" being broken isn't meaningful enough to mention.
    if broken >= 2:
        return "No worries about the gap. What matters is you're here now."
    return ""


def _milestone_hit(previous: int | None, current: int, target: int) -> int | None:
    """Return 25, 50, or 75 if this check-in crossed that threshold; else None.

    A threshold counts as "just crossed" when the previous value was below it
    and the current value is at-or-above. Higher thresholds win when more than
    one was crossed in a single jump.
    """
    # Need a real prior data point to claim a crossing; otherwise we'd fire
    # "just crossed 25%" on a first check-in that simply happens to be above 25%.
    if target <= 0 or previous is None:
        return None
    prev_pct = previous / target * 100
    curr_pct = current / target * 100
    for t in (75, 50, 25):
        if prev_pct < t <= curr_pct:
            return t
    return None


# ---- composition: situation -> (tone, message, action) --------------------

def _compose(
    *,
    name: str,
    title: str,
    current: int,
    target: int,
    previous: int | None,
    mood: str,
    trend: str,
    days_silent: int,
    milestone: int | None,
    progress_pct: float,
    expected_pct: float,
    days_left: int,
) -> tuple[str, str, str]:
    remaining = max(0, target - current)

    # Highest priority: goal complete trumps everything.
    if current >= target:
        return (
            "celebration",
            f"{name}, you did it -- {title} is in the bag. That's the kind of "
            f"follow-through most people only talk about. Take a beat to actually "
            f"feel this win before reaching for the next thing.",
            "Write down one thing you learned about yourself from finishing this.",
        )

    # Silence overrides mood -- get them back in the door first.
    if days_silent >= 3:
        return (
            "reengagement",
            f"{name}, it's been {days_silent} days -- no judgment. The hardest part "
            f"of any long stretch is coming back, and you're here. Let's not try to "
            f"catch up yet; let's just rejoin.",
            "Spend 10 minutes today getting reacquainted with the goal. Don't try to recover ground yet.",
        )

    # Milestone celebrations beat mood-based dispatch -- crossing 25/50/75 is a moment.
    if milestone is not None:
        label = {
            75: "three-quarters of the way",
            50: "halfway",
            25: "a quarter of the way",
        }[milestone]
        return (
            "celebration",
            f"{name}, you just crossed {label} on {title} -- {current}/{target}. "
            f"That's not a small thing; it's the part most people quit before reaching. "
            f"Let yourself feel this.",
            "Take five minutes today to write what's working so far -- you'll need that map in the harder stretches ahead.",
        )

    # ---- mood + trend specifics (the heart of the smarter logic) ----

    if mood == "frustrated" and trend == "declining":
        return (
            "empathy",
            f"{name}, this is genuinely hard, and slipping backwards on something you "
            f"care about is one of the worst feelings. Plenty of people quit at exactly "
            f"this point -- you're not weak for finding it heavy. The way through isn't "
            f"a bigger push; it's a smaller next move.",
            "Do the smallest possible version of one step today -- something so easy it feels almost pointless. That's the whole assignment.",
        )

    if mood == "frustrated" and trend == "improving":
        # Reframe: feelings say stuck, numbers say moving. Show the exact gap.
        delta = current - (previous or 0)
        return (
            "motivational",
            f"{name}, I hear that this feels stuck -- and I want you to actually look "
            f"at the numbers, because they don't agree with the feeling. You went from "
            f"{previous} to {current} (+{delta}). I know it doesn't feel like it, but "
            f"you ARE moving forward.",
            "Today, do exactly the same thing you did last session. Don't try to escalate -- the consistency is what's working.",
        )

    if mood == "happy" and progress_pct >= expected_pct + 10:
        return (
            "celebration",
            f"{name}, you're not just on pace -- you're ahead. {current}/{target} is real "
            f"ground, and the energy you've got right now is rare. Don't waste this window.",
            "Pick one stretch -- a harder version of your usual rep, an extra session this week, a tougher target -- and do it while the momentum is hot.",
        )

    if mood == "neutral" and abs(progress_pct - expected_pct) <= 10:
        per_day = max(1, -(-remaining // max(days_left, 1)))  # ceil division
        return (
            "motivational",
            f"{name}, you're moving at a real, sustainable pace on {title} -- "
            f"{current}/{target}, right on track. The boring middle is where most goals "
            f"are actually won.",
            f"Lock in {per_day} today -- same time, same place. Protect the rhythm.",
        )

    # ---- fallbacks for combos not specialized above ----

    if mood == "happy":
        return (
            "celebration",
            f"{name}, that's a real win on {title}. You're at {current}/{target} -- "
            f"let yourself feel this before reaching for the next step. Moments like "
            f"this are what carry you to the finish.",
            "Set up your very next step today, while the momentum is fresh.",
        )

    if mood in ("frustrated", "anxious"):
        return (
            "empathy",
            f"{name}, hard stretches are part of this -- they don't undo what you've "
            f"already done on {title}. You don't need a perfect week. You need one "
            f"honest next step.",
            "Do the smallest possible version of one step today. That's the whole assignment.",
        )

    # neutral, well off-pace
    if progress_pct < expected_pct - 25:
        return (
            "reengagement",
            f"{name}, it's been a slow stretch on {title}. No judgment -- let's just "
            f"shrink the next move until starting feels easy again.",
            "Spend 10 minutes -- just 10 -- getting reacquainted with the goal. Don't try to catch up yet.",
        )

    # neutral catchall
    per_day = max(1, -(-remaining // max(days_left, 1)))
    return (
        "motivational",
        f"You're moving, {name}. {remaining} to go on {title}, and {days_left} days to "
        f"do it. The shape of this is working -- keep showing up.",
        f"Lock in {per_day} today -- same time, same place.",
    )


# ---- public API -----------------------------------------------------------

def generate_coach_response(
    *,
    name: str,
    title: str,
    current_value: int,
    target_value: int,
    created_at: str,
    target_date: str,
    mood: str,
    today: date | None = None,
    # New optional signals -- callers without prior-checkin context can omit.
    previous_value: int | None = None,
    last_checkin_at: str | None = None,
    # All prior check-in created_at strings (any order). Used for streak math.
    # If supplied, last_checkin_at is derived from it when not given separately.
    prior_checkin_dates: list[str] | None = None,
) -> CoachResponse:
    today = today or date.today()
    progress_pct = min(100.0, (current_value / target_value) * 100) if target_value else 0.0
    expected_pct = _expected_progress_pct(created_at, target_date, today)
    days_left = max(0, (date.fromisoformat(target_date) - today).days)

    # If the caller passed the full date list but not last_checkin_at, derive it
    # so silence detection still works without forcing both params.
    if last_checkin_at is None and prior_checkin_dates:
        last_checkin_at = max(prior_checkin_dates)

    trend = _trend(current_value, previous_value)
    days_silent = _days_silent(last_checkin_at, today)
    milestone = _milestone_hit(previous_value, current_value, target_value)
    streak_days, broken_streak = _compute_streaks(today, prior_checkin_dates)

    tone, message, action = _compose(
        name=name,
        title=title,
        current=current_value,
        target=target_value,
        previous=previous_value,
        mood=mood,
        trend=trend,
        days_silent=days_silent,
        milestone=milestone,
        progress_pct=progress_pct,
        expected_pct=expected_pct,
        days_left=days_left,
    )

    return {
        "message": message,
        "tone": tone,
        "action_item": action,
        "progress_assessment": _assessment(progress_pct, expected_pct),
        "days_until_next_checkin": _next_checkin_days(tone),
        "streak_days": streak_days,
        "streak_callout": _streak_callout(streak_days, broken_streak),
    }
