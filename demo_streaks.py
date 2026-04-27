"""Demo the streak detection in coach.generate_coach_response().

Each scenario constructs a list of prior check-in dates relative to a fixed
"today" so you can see exactly how the streak logic responds:
  - active 3+ day streak    -> consistency callout
  - active 5 day streak     -> same callout, larger N
  - first-ever check-in     -> streak_days=1, no callout
  - day 2 (not yet 3)       -> streak_days=2, no callout (too short to call out)
  - just broke a 4-day run  -> gentle gap acknowledgment
  - 1-day "streak" broken   -> no callout (1 day isn't a meaningful streak)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from coach import generate_coach_response

TODAY = date(2026, 4, 27)


def _days_ago(*offsets: int) -> list[str]:
    """ISO datetime strings for the given day-offsets back from TODAY."""
    return [(TODAY - timedelta(days=n)).isoformat() + "T12:00:00" for n in offsets]


@dataclass
class Scenario:
    label: str
    prior_offsets: list[int] = field(default_factory=list)

    def call(self) -> dict:
        return generate_coach_response(
            name="Sam",
            title="Run 30 training sessions",
            current_value=10,
            target_value=30,
            created_at=(TODAY - timedelta(days=20)).isoformat() + "T00:00:00",
            target_date=(TODAY + timedelta(days=40)).isoformat(),
            mood="neutral",
            today=TODAY,
            prior_checkin_dates=_days_ago(*self.prior_offsets),
        )


SCENARIOS = [
    # Yesterday + day-before-yesterday -> today is day 3 of a run.
    Scenario("Active 3-day streak           (today is day 3)", [1, 2]),
    # 1..4 days ago all checked in -> today is day 5.
    Scenario("Active 5-day streak           (today is day 5)", [1, 2, 3, 4]),
    # No priors at all.
    Scenario("First-ever check-in           (no prior data)",  []),
    # Yesterday only -> today is day 2 of a run, not yet long enough to mention.
    Scenario("Day 2 of a run                (too short to call out)", [1]),
    # Run of 4 days that ended 3+ days ago, no check-in yesterday or day-before -> broken.
    # Last prior was 3d ago, then 4,5,6 days ago. Gap between today and 3d ago.
    Scenario("Just broke a 4-day streak     (gap before today)", [3, 4, 5, 6]),
    # One-off check-in 3 days ago -- broken=1 only, not a real streak.
    Scenario("Broken 1-day 'streak'         (gap, but never a real streak)", [3]),
]


def main() -> None:
    print("=" * 72)
    print(" Streak detection demo  (today = 2026-04-27)")
    print("=" * 72)
    for s in SCENARIOS:
        offsets_str = (
            ", ".join(f"{o}d ago" for o in s.prior_offsets) if s.prior_offsets else "none"
        )
        r = s.call()
        sep = "-" * 72
        print()
        print(sep)
        print(f"  SCENARIO       : {s.label}")
        print(f"  prior dates    : {offsets_str}")
        print(f"  streak_days    : {r['streak_days']}")
        print(f"  streak_callout : {r['streak_callout']!r}")
        print(f"  tone           : {r['tone']}")
        print(f"  message        : {r['message']}")
    print("=" * 72)


if __name__ == "__main__":
    main()
