"""Shape contract test for coach.generate_coach_response().

Runs four very different scenarios and verifies every response has:
  - a real message (non-empty string)
  - tone in the four allowed values
  - a clear action_item
  - a clear progress_assessment
  - a positive integer days_until_next_checkin

Prints every scenario's response in a uniform layout so they read side by side.
Exits 0 if all contract checks pass, 1 otherwise.

Run: python test_coach.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

from coach import VALID_TONES, generate_coach_response

EXPECTED_KEYS = {
    "message",
    "tone",
    "action_item",
    "progress_assessment",
    "days_until_next_checkin",
    "streak_days",
    "streak_callout",
}

TODAY = date.today()


@dataclass
class Scenario:
    label: str
    name: str
    title: str
    current_value: int
    target_value: int
    created_days_ago: int
    target_days_from_now: int
    mood: str

    def call(self) -> dict:
        return generate_coach_response(
            name=self.name,
            title=self.title,
            current_value=self.current_value,
            target_value=self.target_value,
            created_at=(TODAY - timedelta(days=self.created_days_ago)).isoformat() + "T00:00:00",
            target_date=(TODAY + timedelta(days=self.target_days_from_now)).isoformat(),
            mood=self.mood,
            today=TODAY,
        )


SCENARIOS = [
    Scenario(
        label="Falling behind & frustrated",
        name="Sam",
        title="Run a half marathon",
        current_value=4,
        target_value=30,           # 30 training runs
        created_days_ago=60,
        target_days_from_now=30,
        mood="frustrated",
    ),
    Scenario(
        label="Steady & neutral",
        name="Priya",
        title="Ship the redesign",
        current_value=30,
        target_value=90,           # 90 design tickets
        created_days_ago=30,
        target_days_from_now=60,
        mood="neutral",
    ),
    Scenario(
        label="Ahead & happy",
        name="Diego",
        title="Read 10 books",
        current_value=10,
        target_value=10,
        created_days_ago=30,
        target_days_from_now=30,
        mood="happy",
    ),
    Scenario(
        label="Gone silent too long",
        name="Alex",
        title="Write a novel draft",
        current_value=2,
        target_value=50,           # 50 chapters
        created_days_ago=90,
        target_days_from_now=5,
        mood="neutral",
    ),
]


# --- assertion helpers that collect failures instead of aborting ----------

failures: list[str] = []


def expect(condition: bool, scenario: str, field: str, expected: str, actual: str) -> None:
    if not condition:
        failures.append(
            f"  [FAIL] {scenario} :: {field}\n"
            f"         expected: {expected}\n"
            f"         actual  : {actual}"
        )


def check_shape(scenario_label: str, response: dict) -> None:
    actual_keys = set(response.keys())
    expect(
        actual_keys == EXPECTED_KEYS,
        scenario_label,
        "response keys",
        f"exactly {sorted(EXPECTED_KEYS)}",
        f"{sorted(actual_keys)} "
        f"(missing: {sorted(EXPECTED_KEYS - actual_keys)}, "
        f"extra: {sorted(actual_keys - EXPECTED_KEYS)})",
    )

    msg = response.get("message")
    expect(
        isinstance(msg, str) and len(msg.strip()) >= 10,
        scenario_label,
        "message",
        "non-empty string with substantive content (>= 10 chars)",
        f"{type(msg).__name__}={msg!r}",
    )

    tone = response.get("tone")
    expect(
        tone in VALID_TONES,
        scenario_label,
        "tone",
        f"one of {VALID_TONES}",
        repr(tone),
    )

    action = response.get("action_item")
    expect(
        isinstance(action, str) and len(action.strip()) >= 5,
        scenario_label,
        "action_item",
        "non-empty string describing one specific next step",
        f"{type(action).__name__}={action!r}",
    )

    assessment = response.get("progress_assessment")
    expect(
        isinstance(assessment, str) and len(assessment.strip()) >= 5,
        scenario_label,
        "progress_assessment",
        "non-empty string describing where the user stands",
        f"{type(assessment).__name__}={assessment!r}",
    )

    days = response.get("days_until_next_checkin")
    # bools are ints in Python — exclude them explicitly.
    expect(
        isinstance(days, int) and not isinstance(days, bool) and days > 0,
        scenario_label,
        "days_until_next_checkin",
        "positive integer",
        f"{type(days).__name__}={days!r}",
    )

    streak = response.get("streak_days")
    expect(
        isinstance(streak, int) and not isinstance(streak, bool) and streak >= 1,
        scenario_label,
        "streak_days",
        "integer >= 1 (today's check-in counts as 1)",
        f"{type(streak).__name__}={streak!r}",
    )

    callout = response.get("streak_callout")
    expect(
        isinstance(callout, str),
        scenario_label,
        "streak_callout",
        "string (possibly empty)",
        f"{type(callout).__name__}={callout!r}",
    )


def render(scenario: Scenario, r: dict) -> str:
    sep = "-" * 72
    return (
        f"{sep}\n"
        f"  SCENARIO            : {scenario.label}\n"
        f"  user                : {scenario.name}\n"
        f"  goal                : {scenario.title}\n"
        f"  state               : {scenario.current_value}/{scenario.target_value}"
        f", created {scenario.created_days_ago}d ago,"
        f" due in {scenario.target_days_from_now}d,"
        f" mood={scenario.mood}\n"
        f"\n"
        f"  tone                : {r.get('tone')}\n"
        f"  message             : {r.get('message')}\n"
        f"  action_item         : {r.get('action_item')}\n"
        f"  progress_assessment : {r.get('progress_assessment')}\n"
        f"  days_until_next     : {r.get('days_until_next_checkin')}\n"
        f"  streak_days         : {r.get('streak_days')}\n"
        f"  streak_callout      : {r.get('streak_callout')!r}\n"
    )


def main() -> int:
    print("=" * 72)
    print(" Coach response contract test")
    print("=" * 72)

    for s in SCENARIOS:
        try:
            r = s.call()
        except Exception as e:
            failures.append(f"  [FAIL] {s.label} :: coach raised {type(e).__name__}: {e}")
            print(f"\n  [{s.label}] CRASHED: {type(e).__name__}: {e}")
            continue
        print()
        print(render(s, r))
        check_shape(s.label, r)

    print("=" * 72)
    if failures:
        print(f" RESULT: FAIL  ({len(failures)} contract violation(s))")
        print("=" * 72)
        for f in failures:
            print(f)
        return 1
    print(f" RESULT: PASS  (all {len(SCENARIOS)} scenarios match the contract)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
