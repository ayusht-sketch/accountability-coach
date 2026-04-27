# Weekly Progress Review

It is 6 PM Sunday. Run a deep weekly review across every active goal
using the deep-thinking analysis in `weekly_review.py`, and flag any
goal at high risk of missing its deadline.

## Goal

For every goal in `coach.db`, gather the last 7 days of check-ins, run
them through `weekly_review.weekly_review()` (which uses Anthropic
Extended Thinking when `ANTHROPIC_API_KEY` is set, falling back to the
local heuristic analyzer otherwise), and produce a single dated report
with insights and recommendations.

## Steps

1. For each goal returned by `database.list_goals()`:
   a. Pull check-ins via `database.list_check_ins(goal_id)`, then keep
      only those whose `created_at` falls within the last 7 days
      (today inclusive).
   b. If fewer than 3 check-ins survived the filter, mark the goal as
      **insufficient data** and skip the analyzer for that goal — note
      this in the output. Pattern detection on 1–2 data points is noise.
   c. Otherwise, map each check-in to the `CheckInDict` shape
      `weekly_review.weekly_review` expects:
      ```
      {
        "date": "YYYY-MM-DD",
        "weekday": "Monday" | ... | "Sunday",
        "mood": "happy" | "neutral" | "frustrated" | "anxious",
        "progress_value": int,   # the cumulative value at that check-in
        "note": str,
      }
      ```
   d. Call `weekly_review.weekly_review(name=..., title=...,
      current_value=..., target_value=..., target_date=...,
      checkins=...)` and capture the `WeeklyReview` result.
   e. Render with `weekly_review.format_review(result, name=...)`.

2. Write everything to `weekly-review-YYYY-MM-DD.md` in the project
   root, with this layout:

   - Top of file: `# Weekly Review — {today}` plus a one-line summary
     of how many goals were analyzed vs. skipped.
   - One section per goal, headed by `## {name} — "{title}"`.
     - For analyzed goals, paste the `format_review` output verbatim
       inside a fenced code block.
     - For insufficient-data goals, just write
       `Insufficient data this week (N check-ins).`

3. After all per-goal sections, add a `## At-Risk Goals` section listing
   any analyzed goal where `result.risk_level == "high"`, one bullet
   each:

       - {name} — "{title}": {risk_explanation}

   If no goals are high-risk, write `None — every goal is on track.`

## Constraints

- **Read-only on the database.**
- Do **not** dump the raw `result.thinking` (Extended Thinking trace)
  into the report. `format_review` already excludes it; don't add it
  back.
- Don't print API keys, tokens, or anything from the environment.
- If `coach.db` is missing or empty, write a one-line note and stop.

## When you're done

Print exactly two lines to stdout:
1. The absolute path of the report file.
2. `Reviewed: N | At-risk: M | Skipped (insufficient data): K`
