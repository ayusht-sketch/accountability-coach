# Morning Coaching Run

You are running an autonomous coaching task for the Accountability Coach
app (Flask + SQLite — code lives in the parent directory). It is 8 AM
local time.

## Goal

For every active goal in `coach.db`, decide whether the user needs a
**follow-up nudge** (they checked in yesterday) or a **we-missed-you
reminder** (they didn't), generate the appropriate coaching message using
the existing `coach.generate_coach_response()` function, and write all of
today's messages to a single dated file.

## Steps

1. Use the existing modules — do not re-implement what's already there:
   - `database.list_goals()` for the active goals.
   - `database.list_check_ins(goal_id)` for each goal's history (already
     ordered DESC by `created_at`).
   - `coach.generate_coach_response(...)` for the actual message.

2. For each goal, classify into one bucket:
   - **follow-up**: the most recent check-in's date == yesterday.
   - **we-missed-you**: there is no check-in, OR the most recent check-in
     is older than yesterday.

3. Generate the message:
   - For both buckets, call `generate_coach_response` with the goal's
     current values, the user's last mood (default `"neutral"` if there's
     no history), and `prior_checkin_dates` set to the full list of prior
     `created_at` strings so streak / silence signals fire correctly.
   - For **we-missed-you** specifically, ensure `last_checkin_at` is at
     least 3 days before today (set it to the actual last check-in if
     it's already that old, otherwise pad the gap). The coach module's
     silence path will then produce a reengagement-tone message
     automatically.

4. Append each goal's output to a single file named
   `daily-coaching-YYYY-MM-DD.md` in the project root, where YYYY-MM-DD is
   today's date. Use this format per goal:

   ```
   ## {name} — "{title}"
   - Bucket: follow-up | we-missed-you
   - Tone: {tone}
   - Message: {coach message}
   - Recommended action: {action_item}
   ```

5. End the file with a summary block:

   ```
   ## Summary
   - Goals coached (follow-up): N
   - Goals reminded (we-missed-you): M
   - Total active goals: N + M
   ```

## Constraints

- **Read-only on the database.** No INSERT, UPDATE, or DELETE.
- Do not delete or overwrite previous days' files. If today's file
  already exists, overwrite it (a re-run on the same day is fine).
- If `coach.db` is missing or has no goals, write a one-line note to the
  daily file and stop — don't crash.
- Use whichever Python is on PATH; the only runtime dep is stdlib
  (database/coach are pure Python except for the optional flask import,
  which we're not exercising here).

## When you're done

Print exactly two lines to stdout:
1. The absolute path of the file you wrote.
2. The summary line (`Goals coached: N | Reminded: M | Total: N+M`).

Cron captures stdout — keep it tight.
