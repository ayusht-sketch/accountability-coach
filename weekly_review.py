"""Deep weekly review -- pattern analysis on a full week of check-ins.

Daily messages are quick reactions; this is the weekly pattern read. The output
is a structured report with five things:
  - progress_trend       : accelerating | steady | decelerating | stalled
  - mood_pattern         : improving | stable | declining | volatile
  - motivation_cycles    : weekday strong/weak observations
  - recommended_strategy : concrete plan for next week
  - risk_level + reason  : likelihood of hitting target by deadline

Tries Anthropic's Extended Thinking first (~5000 reasoning tokens) so the model
can chew on cross-day patterns before answering. Falls back to a local
heuristic implementation when the SDK is missing or ANTHROPIC_API_KEY is unset
-- same shape, same reasoning steps, just no LLM. The lesson is the pattern,
not the API call.
"""
from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TypedDict


# Numeric encoding so we can compute mood trend / volatility. 0 = lowest.
MOOD_SCORE = {"anxious": 0, "frustrated": 1, "neutral": 2, "happy": 3}

THINKING_BUDGET = 5000
MAX_TOKENS = 8000  # must exceed thinking budget; the API rejects otherwise
MODEL = "claude-sonnet-4-6"

COST_NOTE = (
    "Extended Thinking used ~5000 budget tokens. Regular call would use ~500. "
    "Reserve this for weekly reviews, not daily check-ins."
)


class CheckInDict(TypedDict):
    date: str            # YYYY-MM-DD
    weekday: str         # Monday, Tuesday, ...
    mood: str            # happy | neutral | frustrated | anxious
    progress_value: int  # cumulative progress as of that day
    note: str


@dataclass
class WeeklyReview:
    progress_trend: str
    mood_pattern: str
    motivation_cycles: str
    recommended_strategy: str
    risk_level: str
    risk_explanation: str
    thinking: str | None = None
    source: str = "local_fallback"  # "anthropic" | "local_fallback"


# ---------------------------------------------------------------------------
# Local reasoning steps -- mirror what we'd ask the LLM to do.
# ---------------------------------------------------------------------------

def _daily_deltas(checkins: list[CheckInDict]) -> list[int]:
    """Per-day progress added. Assumes checkins are chronological."""
    deltas: list[int] = []
    prev = 0
    for c in checkins:
        deltas.append(c["progress_value"] - prev)
        prev = c["progress_value"]
    return deltas


def _trend_from_deltas(deltas: list[int]) -> str:
    if not deltas or sum(deltas) == 0:
        return "stalled"
    half = len(deltas) // 2
    first = sum(deltas[:half]) / max(half, 1)
    second = sum(deltas[half:]) / max(len(deltas) - half, 1)
    # No second-half progress while first half had some = effort dropped to zero.
    if second == 0 and first > 0:
        return "decelerating"
    if first == 0:
        return "accelerating" if second > 0 else "stalled"
    ratio = second / first
    if ratio >= 1.2:
        return "accelerating"
    if ratio <= 0.8:
        return "decelerating"
    return "steady"


def _mood_pattern(checkins: list[CheckInDict]) -> str:
    scores = [MOOD_SCORE.get(c["mood"], 1) for c in checkins]
    if len(scores) < 2:
        return "stable"
    stdev = statistics.pstdev(scores)
    half = len(scores) // 2
    first_avg = sum(scores[:half]) / max(half, 1)
    second_avg = sum(scores[half:]) / max(len(scores) - half, 1)
    delta = second_avg - first_avg
    # High variance with no clear direction = volatile.
    if stdev >= 1.0 and abs(delta) < 0.5:
        return "volatile"
    if delta >= 0.5:
        return "improving"
    if delta <= -0.5:
        return "declining"
    return "stable"


def _motivation_cycles(checkins: list[CheckInDict], deltas: list[int]) -> str:
    by_day: dict[str, list[int]] = {}
    for c, d in zip(checkins, deltas):
        by_day.setdefault(c["weekday"], []).append(d)
    if not by_day:
        return "Not enough data to identify weekday patterns."
    avgs = {day: sum(v) / len(v) for day, v in by_day.items()}
    spread = max(avgs.values()) - min(avgs.values())
    if spread < 1:
        return "Effort is fairly evenly distributed across weekdays."
    sorted_days = sorted(avgs.items(), key=lambda kv: kv[1], reverse=True)
    strong = [d for d, v in sorted_days if v == sorted_days[0][1] and v > 0]
    weak = [d for d, v in sorted_days if v == sorted_days[-1][1]]
    parts = []
    if strong:
        parts.append(f"Strongest day(s): {', '.join(strong)}")
    if weak and weak != strong:
        parts.append(f"weakest day(s): {', '.join(weak)}")
    return "; ".join(parts) + "."


def _risk(
    current_value: int,
    target_value: int,
    target_date: str,
    today: date,
    deltas: list[int],
) -> tuple[str, str]:
    remaining = max(0, target_value - current_value)
    days_left = max(0, (date.fromisoformat(target_date) - today).days)
    if remaining == 0:
        return "low", "Target already reached."
    if days_left == 0:
        return "high", f"Deadline passed with {remaining} units still to go."
    needed = remaining / days_left
    # Use last 3 days as the "recent pace" -- single-day noise overrides week-old momentum.
    window = deltas[-3:] if len(deltas) >= 3 else deltas
    recent = sum(window) / max(len(window), 1)
    if recent == 0:
        return "high", (
            f"Recent pace is zero; need {needed:.1f}/day for {days_left} more days "
            f"to hit {target_value}."
        )
    ratio = recent / needed
    if ratio >= 1.0:
        return "low", (
            f"Recent pace of {recent:.1f}/day covers needed {needed:.1f}/day."
        )
    if ratio >= 0.6:
        return "medium", (
            f"Recent pace of {recent:.1f}/day is below needed {needed:.1f}/day "
            f"-- closeable but won't fix itself."
        )
    return "high", (
        f"Recent pace of {recent:.1f}/day is far below needed {needed:.1f}/day."
    )


def _strategy(trend: str, mood: str, risk: str) -> str:
    parts: list[str] = []
    if trend == "decelerating":
        parts.append(
            "Front-load the week -- bank progress Monday/Tuesday before the mid-week dip."
        )
    elif trend == "accelerating":
        parts.append("Protect what's working -- keep the same time/place that drove the late-week push.")
    elif trend == "stalled":
        parts.append("Restart small -- pick the tiniest credible step and do it tomorrow; no recovery plan yet.")
    else:
        parts.append("Keep cadence; small consistency beats big bursts here.")

    if mood == "declining":
        parts.append("Mood is sliding -- schedule one recovery moment (rest, friend, walk) before next week starts.")
    elif mood == "volatile":
        parts.append("Mood is jagged -- anchor one fixed daily ritual to flatten the swings.")

    if risk == "high":
        parts.append("Renegotiate the target or deadline now, while you can do it deliberately.")
    return " ".join(parts)


def _local_review(
    name: str,
    title: str,
    current_value: int,
    target_value: int,
    target_date: str,
    today: date,
    checkins: list[CheckInDict],
) -> WeeklyReview:
    deltas = _daily_deltas(checkins)
    trend = _trend_from_deltas(deltas)
    mood = _mood_pattern(checkins)
    cycles = _motivation_cycles(checkins, deltas)
    risk_level, risk_explanation = _risk(
        current_value, target_value, target_date, today, deltas
    )
    strategy = _strategy(trend, mood, risk_level)
    return WeeklyReview(
        progress_trend=trend,
        mood_pattern=mood,
        motivation_cycles=cycles,
        recommended_strategy=strategy,
        risk_level=risk_level,
        risk_explanation=risk_explanation,
        thinking=None,
        source="local_fallback",
    )


# ---------------------------------------------------------------------------
# Anthropic Extended Thinking path.
# ---------------------------------------------------------------------------

def _build_prompt(
    name: str,
    title: str,
    current_value: int,
    target_value: int,
    target_date: str,
    today: date,
    checkins: list[CheckInDict],
) -> str:
    lines = [
        f"You are reviewing one week of check-ins for {name}, who is working on:",
        f'  Goal: "{title}"',
        f"  Current progress: {current_value}/{target_value}",
        f"  Target deadline: {target_date} (today is {today.isoformat()})",
        "",
        "Check-ins (chronological):",
    ]
    for c in checkins:
        note = f' -- note: "{c["note"]}"' if c["note"] else ""
        lines.append(
            f"  {c['date']} ({c['weekday']}): mood={c['mood']}, "
            f"cumulative_progress={c['progress_value']}{note}"
        )
    lines += [
        "",
        "Think carefully about patterns across the week -- not just what happened "
        "day-by-day, but how mood and effort interact, where the user fades, and "
        "where they peak. Cross-reference the mood timeline against the progress "
        "deltas. Consider whether the deadline is realistically reachable at the "
        "current pace.",
        "",
        "Respond with ONE JSON object and nothing else, with these exact keys:",
        '  "progress_trend"      : one of "accelerating", "steady", "decelerating", "stalled"',
        '  "mood_pattern"        : one of "improving", "stable", "declining", "volatile"',
        '  "motivation_cycles"   : short paragraph naming strong/weak weekdays you observed',
        '  "recommended_strategy": concrete plan for next week (2-4 sentences, specific)',
        '  "risk_level"          : one of "low", "medium", "high"',
        '  "risk_explanation"    : one sentence explaining the risk call',
    ]
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Sometimes models wrap JSON in prose or fences -- grab the outermost {...}.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _try_anthropic(
    name: str,
    title: str,
    current_value: int,
    target_value: int,
    target_date: str,
    today: date,
    checkins: list[CheckInDict],
) -> WeeklyReview | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        name, title, current_value, target_value, target_date, today, checkins
    )

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        # Network/auth/quota errors → silently fall back rather than crash the caller.
        print(f"[weekly_review] Anthropic call failed ({type(e).__name__}: {e}); using local fallback.")
        return None

    thinking_text = ""
    text_text = ""
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "thinking":
            thinking_text += getattr(block, "thinking", "")
        elif btype == "text":
            text_text += getattr(block, "text", "")

    payload = _extract_json(text_text)
    if not payload:
        print("[weekly_review] Could not parse JSON from model output; using local fallback.")
        return None

    return WeeklyReview(
        progress_trend=payload.get("progress_trend", "steady"),
        mood_pattern=payload.get("mood_pattern", "stable"),
        motivation_cycles=payload.get("motivation_cycles", ""),
        recommended_strategy=payload.get("recommended_strategy", ""),
        risk_level=payload.get("risk_level", "medium"),
        risk_explanation=payload.get("risk_explanation", ""),
        thinking=thinking_text or None,
        source="anthropic",
    )


# ---------------------------------------------------------------------------
# Public entrypoint + formatter.
# ---------------------------------------------------------------------------

def weekly_review(
    *,
    name: str,
    title: str,
    current_value: int,
    target_value: int,
    target_date: str,
    checkins: list[CheckInDict],
    today: date | None = None,
) -> WeeklyReview:
    today = today or date.today()
    # Sort defensively -- every downstream calc assumes chronological order.
    checkins = sorted(checkins, key=lambda c: c["date"])
    result = _try_anthropic(
        name, title, current_value, target_value, target_date, today, checkins
    )
    return result or _local_review(
        name, title, current_value, target_value, target_date, today, checkins
    )


def format_review(review: WeeklyReview, *, name: str = "User") -> str:
    bar = "=" * 64
    return "\n".join([
        bar,
        f"  WEEKLY REVIEW -- {name}",
        f"  Source: {review.source}",
        bar,
        "",
        f"PROGRESS TREND      : {review.progress_trend}",
        f"MOOD PATTERN        : {review.mood_pattern}",
        "",
        "MOTIVATION CYCLES",
        f"  {review.motivation_cycles}",
        "",
        "RISK ASSESSMENT",
        f"  Level: {review.risk_level}",
        f"  {review.risk_explanation}",
        "",
        "RECOMMENDED STRATEGY",
        f"  {review.recommended_strategy}",
        "",
        bar,
        COST_NOTE,
        bar,
    ])


# ---------------------------------------------------------------------------
# Demo: a fake user with strong Mon/Tue and fading Thu/Fri.
# ---------------------------------------------------------------------------

def _demo() -> None:
    today = date(2026, 4, 27)  # Monday -- the next week starts now
    week_start = today - timedelta(days=7)  # previous Monday

    # Cumulative progress: hard pushes Mon/Tue, fading mid-week, near-zero weekend.
    cumulative = [5, 10, 13, 14, 15, 15, 15]
    moods = ["happy", "happy", "neutral", "frustrated", "frustrated", "anxious", "anxious"]
    notes = [
        "fresh start, feels great",
        "got a chunk done before lunch",
        "harder today but stuck with it",
        "exhausted, only half a session",
        "couldn't focus -- kept getting pulled away",
        "didn't really get to it",
        "just checking in, need a reset",
    ]
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    checkins: list[CheckInDict] = [
        {
            "date": (week_start + timedelta(days=i)).isoformat(),
            "weekday": weekdays[i],
            "mood": moods[i],
            "progress_value": cumulative[i],
            "note": notes[i],
        }
        for i in range(7)
    ]

    review = weekly_review(
        name="Sam",
        title="Run 50km this month",
        current_value=15,
        target_value=50,
        target_date="2026-05-15",
        today=today,
        checkins=checkins,
    )

    if review.thinking:
        print("=" * 64)
        print("  EXTENDED THINKING TRACE")
        print("=" * 64)
        print(review.thinking)
        print()

    print(format_review(review, name="Sam"))


if __name__ == "__main__":
    _demo()
