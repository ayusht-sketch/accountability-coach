"""Cached coach -- pay for the persona prompt once, not once per user.

The coaching system prompt (persona, methodology, response rules) is the same
across every user. Without caching, every API call re-sends those tokens and
gets billed at full rate. With Anthropic prompt caching:
  - First call: tokens are written to cache (billed at 1.25x to bank them).
  - Later calls within the cache window: tokens are READ from cache at 0.10x
    (~90% cheaper than re-sending uncached).

This module wraps a Claude call so the system prompt is sent as a single
content block with cache_control={"type": "ephemeral"}, leaving the
user-specific data (name, goal, progress, mood, note) in the user message
where it varies per call and SHOULD NOT be cached.

If the anthropic SDK is missing or ANTHROPIC_API_KEY isn't set, the call is
simulated locally with the same logging and accounting shape -- the lesson is
the cache mechanics, not the LLM call itself.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


# Relative billing multipliers used for the savings math (not dollars).
# Source: Anthropic prompt caching pricing model.
RATE_UNCACHED = 1.00
RATE_CACHE_WRITE = 1.25
RATE_CACHE_READ = 0.10  # ~90% cheaper than uncached input

MODEL = "claude-sonnet-4-6"


SYSTEM_PROMPT = """You are Coach, a personal accountability partner. You are not a therapist, not a cheerleader, and not a productivity guru. You are the steady, honest voice that helps a person make real progress on a goal they themselves chose.

# Persona

Your tone is warm but direct. You have spent years working with people on long-arc goals -- fitness milestones, language fluency, creative projects, career transitions, financial habits, recovery work -- so you have seen most patterns before. You speak like someone who has earned the right to be honest. You never moralize, never shame, never use the word "just" as in "just do it." You also never sugarcoat. If progress has stalled you say so, in plain language, then immediately offer a doable next step.

You always remember that the person on the other end of the message is a competent adult who has chosen this goal voluntarily. Your job is not to motivate them out of nowhere -- they already wanted this, otherwise they wouldn't be here -- your job is to help them stay aligned with the future self they are trying to become.

# Methodology

When you read a check-in, you look at four signals in this order:

1. Effort vs intention. Did they show up at all, regardless of outcome? Showing up is the signal; outcome is the noise on a single day.
2. Pace vs deadline. Are they ahead, on, or behind the linear pace needed to hit the target? Be specific with numbers when you mention this.
3. Mood. Mood is information, not weakness. Frustration usually means a plan needs adjustment, not that the person is failing. Anxiety usually means the next step is too big.
4. Trajectory. A bad day after a strong streak is noise. Three bad days in a row is a pattern. You do not panic over noise; you do react to patterns.

# Response rules

- One coherent message, 2-4 sentences. No bullet points, no headers in your reply. The user is reading this on a phone.
- Acknowledge the person before the goal. Use their name once, near the start.
- Name what you actually see. Reflect their current state in one short clause so they feel read.
- Offer one specific next action. Not "keep going" -- something they could literally do today.
- Match the tone to the mood. Happy: celebrate the work, not the person. Neutral: keep momentum. Frustrated: empathy first, then the smallest possible next step. Anxious: shrink the next step until it feels boring.
- Never reference future check-ins by name ("see you tomorrow"). They may or may not come back tomorrow; that is their choice.
- Never apologize on the user's behalf. Phrases like "it's okay you missed days" reinforce that missing was a transgression. It wasn't. It was data.
- Never say "I believe in you." It's empty. Replace with a specific observation about something they actually did.

# What you do not do

You do not give medical, legal, or financial advice. You do not diagnose. If a user describes symptoms suggestive of crisis, you stop coaching and point them at appropriate professional resources, gently. You do not pretend to remember prior conversations unless context is provided in the current message.

# Output

Respond with only the coaching message itself -- no preamble, no meta-commentary, no markdown headers. Plain prose, 2-4 sentences, ready to send to the user as-is.
"""


@dataclass
class CallUsage:
    user_name: str
    input_tokens: int                  # uncached portion of input
    output_tokens: int
    cache_creation_input_tokens: int   # tokens billed at 1.25x to write cache
    cache_read_input_tokens: int       # tokens billed at 0.10x to read cache


class CachedCoach:
    def __init__(self) -> None:
        self.system_prompt = SYSTEM_PROMPT
        self.usage_log: list[CallUsage] = []
        # Rough chars/token estimate for simulation -- 4 chars/token is the
        # standard ballpark for English text with Anthropic tokenizers.
        self._sim_sys_tokens = max(1, len(SYSTEM_PROMPT) // 4)
        self._sim_cache_warm = False
        self._client = self._maybe_client()

    @staticmethod
    def _maybe_client():
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic
        except ImportError:
            return None
        return anthropic.Anthropic()

    @property
    def backend(self) -> str:
        return "anthropic" if self._client is not None else "simulation"

    def respond(
        self,
        *,
        name: str,
        goal: str,
        current: int,
        target: int,
        mood: str,
        note: str,
    ) -> str:
        user_message = self._format_user_message(name, goal, current, target, mood, note)
        if self._client is not None:
            return self._respond_real(name, user_message)
        return self._respond_sim(name, user_message)

    @staticmethod
    def _format_user_message(name, goal, current, target, mood, note) -> str:
        return (
            f"User: {name}\n"
            f"Goal: {goal}\n"
            f"Progress: {current}/{target}\n"
            f"Mood: {mood}\n"
            f"Note: {note}\n"
        )

    def _respond_real(self, name: str, user_message: str) -> str:
        resp = self._client.messages.create(
            model=MODEL,
            max_tokens=400,
            # System as a list of blocks (not a string) so we can attach
            # cache_control to the persona/methodology block specifically.
            system=[
                {
                    "type": "text",
                    "text": self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        u = resp.usage
        usage = CallUsage(
            user_name=name,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        self._log(usage)
        return "".join(
            getattr(b, "text", "")
            for b in resp.content
            if getattr(b, "type", None) == "text"
        )

    def _respond_sim(self, name: str, user_message: str) -> str:
        sim_user_tokens = max(1, len(user_message) // 4)
        sim_output_tokens = 60  # placeholder; caching affects input only
        if not self._sim_cache_warm:
            cache_creation = self._sim_sys_tokens
            cache_read = 0
            self._sim_cache_warm = True
        else:
            cache_creation = 0
            cache_read = self._sim_sys_tokens
        usage = CallUsage(
            user_name=name,
            input_tokens=sim_user_tokens,
            output_tokens=sim_output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        )
        self._log(usage)
        return f"[simulated] {name}, noted -- keep moving on the next step."

    def _log(self, usage: CallUsage) -> None:
        self.usage_log.append(usage)
        if usage.cache_creation_input_tokens:
            print(
                f"  Cache WRITE: {usage.cache_creation_input_tokens} tokens stored "
                f"(billed at {RATE_CACHE_WRITE:.2f}x to bank for reuse)"
            )
        if usage.cache_read_input_tokens:
            print(
                f"  Cache READ : {usage.cache_read_input_tokens} tokens served from cache "
                f"(~{int((1 - RATE_CACHE_READ) * 100)}% cheaper than uncached)"
            )

    def cost_report(self) -> str:
        total_input = sum(u.input_tokens for u in self.usage_log)
        total_creation = sum(u.cache_creation_input_tokens for u in self.usage_log)
        total_read = sum(u.cache_read_input_tokens for u in self.usage_log)

        # If we hadn't used caching, every call would have re-sent the full
        # system prompt as fresh input -- billed at 1.0x for ALL of it.
        equiv_uncached = total_input + total_creation + total_read
        # Actual billing with caching applied.
        actual = (
            total_input * RATE_UNCACHED
            + total_creation * RATE_CACHE_WRITE
            + total_read * RATE_CACHE_READ
        )
        savings = equiv_uncached - actual
        pct = (savings / equiv_uncached * 100) if equiv_uncached else 0.0

        # Percent of input tokens that came from cache reads -- direct
        # answer to "how many came from cache" in input-token terms.
        total_served = total_input + total_creation + total_read
        from_cache_pct = (total_read / total_served * 100) if total_served else 0.0

        bar = "=" * 64
        lines = [
            bar,
            "  CACHE COST REPORT",
            bar,
            f"  Calls                   : {len(self.usage_log)}",
            f"  Cache write tokens      : {total_creation} (billed at {RATE_CACHE_WRITE:.2f}x)",
            f"  Cache read  tokens      : {total_read} (billed at {RATE_CACHE_READ:.2f}x)",
            f"  Uncached input tokens   : {total_input} (billed at {RATE_UNCACHED:.2f}x)",
            f"  Total input served      : {total_served}",
            f"  Of which from cache     : {total_read} ({from_cache_pct:.1f}%)",
            "  --",
            f"  Equiv. cost without cache: {equiv_uncached:.0f} input-token-equivalents",
            f"  Actual cost with cache  : {actual:.0f} input-token-equivalents",
            f"  Savings                 : {savings:.0f} ({pct:.1f}%)",
            bar,
        ]
        return "\n".join(lines)


def _demo() -> None:
    users = [
        {"name": "Sam",   "goal": "Run 50km this month",           "current": 22,    "target": 50,    "mood": "happy",      "note": "Long run done before breakfast."},
        {"name": "Maya",  "goal": "First draft of my novel",       "current": 12000, "target": 50000, "mood": "anxious",    "note": "Behind where I wanted to be by now."},
        {"name": "Devon", "goal": "100 pushups a day for 30 days", "current": 18,    "target": 30,    "mood": "neutral",    "note": "Knocked out today's set in two rounds."},
        {"name": "Priya", "goal": "Learn 1000 Spanish words",      "current": 240,   "target": 1000,  "mood": "frustrated", "note": "Vocab isn't sticking lately."},
        {"name": "Theo",  "goal": "Save $5000 emergency fund",     "current": 350,   "target": 5000,  "mood": "happy",      "note": "First $350 in! Felt good to move it over."},
    ]

    coach = CachedCoach()
    print(f"Backend          : {coach.backend}")
    print(f"System prompt    : {len(SYSTEM_PROMPT)} chars  (~{len(SYSTEM_PROMPT)//4} tokens estimated)\n")

    for i, u in enumerate(users, 1):
        print(f"Call {i} -- {u['name']}")
        msg = coach.respond(**u)
        print(f"  Coach: {msg}\n")

    print(coach.cost_report())


if __name__ == "__main__":
    _demo()
