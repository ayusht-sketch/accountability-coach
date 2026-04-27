"""Demo the new mood+trend behavior in coach.generate_coach_response().

Each scenario isolates one of the new branches so you can see the dispatch
working: declining-while-frustrated empathy, frustrated-but-actually-improving
reframe, neutral on-track steadiness, happy-and-ahead stretch challenge,
3-day-silence reengagement, and a milestone crossing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from coach import generate_coach_response

TODAY = date(2026, 4, 27)


@dataclass
class Scenario:
    label: str
    name: str
    title: str
    target: int
    current: int
    previous: int | None
    created_days_ago: int
    target_days_from_now: int
    mood: str
    last_checkin_days_ago: int | None  # None = no prior check-in

    def call(self) -> dict:
        last_at = (
            (TODAY - timedelta(days=self.last_checkin_days_ago)).isoformat() + "T00:00:00"
            if self.last_checkin_days_ago is not None
            else None
        )
        return generate_coach_response(
            name=self.name,
            title=self.title,
            current_value=self.current,
            target_value=self.target,
            created_at=(TODAY - timedelta(days=self.created_days_ago)).isoformat() + "T00:00:00",
            target_date=(TODAY + timedelta(days=self.target_days_from_now)).isoformat(),
            mood=self.mood,
            today=TODAY,
            previous_value=self.previous,
            last_checkin_at=last_at,
        )


SCENARIOS = [
    Scenario(
        # Portfolio shrunk because the user scrapped two pages -- same data
        # would happen if a user mis-logged a number lower than before.
        label="Frustrated + declining  -> deep empathy",
        name="Sam",
        title="Build a 30-page portfolio",
        target=30, current=8, previous=10,
        created_days_ago=20, target_days_from_now=40,
        mood="frustrated",
        last_checkin_days_ago=1,
    ),
    Scenario(
        label="Frustrated + improving  -> reframe with the numbers",
        name="Maya",
        title="Write 50,000 words of the novel draft",
        target=50000, current=12000, previous=8000,
        created_days_ago=20, target_days_from_now=40,
        mood="frustrated",
        last_checkin_days_ago=1,
    ),
    Scenario(
        label="Neutral + on track       -> steady encouragement + rhythm lock",
        name="Priya",
        title="Ship the redesign (90 tickets)",
        target=90, current=12, previous=10,
        created_days_ago=12, target_days_from_now=78,
        mood="neutral",
        last_checkin_days_ago=1,
    ),
    Scenario(
        label="Happy + ahead            -> celebrate hard, then stretch challenge",
        name="Diego",
        title="Read 30 books this year",
        target=30, current=25, previous=22,
        created_days_ago=180, target_days_from_now=185,
        mood="happy",
        last_checkin_days_ago=2,
    ),
    Scenario(
        label="3+ day silence           -> gentle reengagement",
        name="Alex",
        title="Run 30 training sessions",
        target=30, current=8, previous=8,
        created_days_ago=40, target_days_from_now=50,
        mood="neutral",
        last_checkin_days_ago=5,
    ),
    Scenario(
        # Crosses 50% (24/50 -> 25/50). Mood happy, but milestone wins.
        label="Crossed 50% milestone    -> milestone celebration",
        name="Theo",
        title="Save $50 in $50K emergency fund (toy units)",
        target=50, current=25, previous=24,
        created_days_ago=60, target_days_from_now=120,
        mood="happy",
        last_checkin_days_ago=1,
    ),
]


def render(s: Scenario, r: dict) -> str:
    sep = "-" * 72
    return (
        f"{sep}\n"
        f"  SCENARIO            : {s.label}\n"
        f"  user                : {s.name}\n"
        f"  goal                : {s.title}\n"
        f"  current/previous    : {s.current}/{s.previous} of {s.target}\n"
        f"  mood                : {s.mood}\n"
        f"  last check-in       : "
        + ("none" if s.last_checkin_days_ago is None else f"{s.last_checkin_days_ago}d ago")
        + "\n\n"
        f"  tone                : {r['tone']}\n"
        f"  message             : {r['message']}\n"
        f"  action_item         : {r['action_item']}\n"
        f"  progress_assessment : {r['progress_assessment']}\n"
        f"  days_until_next     : {r['days_until_next_checkin']}\n"
    )


def main() -> None:
    print("=" * 72)
    print(" Smart coach -- mood+trend scenario demo")
    print("=" * 72)
    for s in SCENARIOS:
        print()
        print(render(s, s.call()))
    print("=" * 72)


if __name__ == "__main__":
    main()
