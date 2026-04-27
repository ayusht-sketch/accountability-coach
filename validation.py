"""Strict input validation. Rejects bad input up front; sanitizes whitespace and
strips control characters. HTML/script tags are rejected outright (defense-in-depth
on top of Jinja's autoescape)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime

# Matches anything that looks like an HTML/script tag opening: <tag, </tag, <!doctype, etc.
_TAG_RE = re.compile(r"<\s*[a-zA-Z!/]")
# Control characters we strip silently (tabs/newlines kept for descriptions).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

ALLOWED_MOODS = {"happy", "neutral", "frustrated", "anxious"}
MAX_NOTE_LEN = 500


class ValidationError(ValueError):
    """Raised with a user-facing message describing what's wrong."""


@dataclass(frozen=True)
class GoalInput:
    name: str
    title: str
    description: str
    target_date: str  # ISO YYYY-MM-DD
    target_value: int


@dataclass(frozen=True)
class CheckInInput:
    goal_id: int
    mood: str
    progress_value: int
    note: str


def _clean(s: str | None) -> str:
    if s is None:
        return ""
    return _CONTROL_RE.sub("", s).strip()


def _reject_tags(field: str, value: str) -> None:
    if _TAG_RE.search(value) or "</" in value:
        raise ValidationError(f"{field} can't contain HTML or script tags.")
    # Also reject literal angle-bracket pairs that escape attempts decode into.
    decoded = html.unescape(value)
    if _TAG_RE.search(decoded) or "</" in decoded:
        raise ValidationError(f"{field} can't contain HTML or script tags.")


def _require_nonblank(field: str, value: str, max_len: int) -> str:
    if not value:
        raise ValidationError(f"{field} is required.")
    if len(value) > max_len:
        raise ValidationError(f"{field} must be {max_len} characters or fewer.")
    _reject_tags(field, value)
    return value


def validate_goal(form: dict) -> GoalInput:
    name = _require_nonblank("Name", _clean(form.get("name")), 100)
    title = _require_nonblank("Goal title", _clean(form.get("title")), 200)

    description = _clean(form.get("description"))
    if len(description) > 1000:
        raise ValidationError("Description must be 1000 characters or fewer.")
    if description:
        _reject_tags("Description", description)

    target_date_raw = _clean(form.get("target_date"))
    if not target_date_raw:
        raise ValidationError("Target date is required.")
    try:
        target_date = datetime.strptime(target_date_raw, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError("Target date must be in YYYY-MM-DD format.")
    if target_date < date.today():
        raise ValidationError("Target date can't be in the past.")

    target_value_raw = _clean(form.get("target_value"))
    if not target_value_raw:
        raise ValidationError("Target value is required.")
    try:
        target_value = int(target_value_raw)
    except ValueError:
        raise ValidationError("Target value must be a whole number.")
    if target_value <= 0:
        raise ValidationError("Target value must be greater than zero.")
    if target_value > 1_000_000:
        raise ValidationError("Target value is unreasonably large.")

    return GoalInput(
        name=name,
        title=title,
        description=description,
        target_date=target_date.isoformat(),
        target_value=target_value,
    )


def validate_check_in(form: dict, max_progress: int) -> CheckInInput:
    goal_id_raw = _clean(form.get("goal_id"))
    try:
        goal_id = int(goal_id_raw)
    except ValueError:
        raise ValidationError("Invalid goal reference.")
    if goal_id <= 0:
        raise ValidationError("Invalid goal reference.")

    mood = _clean(form.get("mood")).lower()
    if mood not in ALLOWED_MOODS:
        raise ValidationError(
            "Mood must be one of: " + ", ".join(sorted(ALLOWED_MOODS)) + "."
        )

    progress_raw = _clean(form.get("progress_value"))
    try:
        progress_value = int(progress_raw)
    except ValueError:
        raise ValidationError("Progress must be a whole number.")
    if progress_value < 0:
        raise ValidationError("Progress can't be negative.")
    if progress_value > max_progress:
        raise ValidationError(
            f"Progress can't exceed the goal's target ({max_progress})."
        )

    note = _clean(form.get("note"))
    if len(note) > MAX_NOTE_LEN:
        raise ValidationError(f"Note must be {MAX_NOTE_LEN} characters or fewer.")
    if note:
        _reject_tags("Note", note)

    return CheckInInput(
        goal_id=goal_id, mood=mood, progress_value=progress_value, note=note
    )
