# Automated Coaching Tasks

Two task definitions that run autonomously via Claude Code in print mode
(`claude --print -p`). Both are read-only against `coach.db` — they
generate dated markdown reports next to the project and do not mutate
state.

| File | Brief | Schedule |
|---|---|---|
| `morning-coaching.md` | Daily nudge for every goal: follow-up if they checked in yesterday, "we missed you" if they didn't | 8 AM every day |
| `weekly-review.md` | Deep weekly analysis (`weekly_review.weekly_review`), flag at-risk goals | 6 PM every Sunday |
| `run-morning-coaching.sh` | Cron-friendly wrapper for the morning task | — |

Outputs land in the project root:
- `daily-coaching-YYYY-MM-DD.md` (daily)
- `weekly-review-YYYY-MM-DD.md` (weekly)

Add those patterns to `.gitignore` if you don't want generated artifacts
in the repo.

## Manual run

Test either task interactively before scheduling it:

    # Morning
    ./tasks/run-morning-coaching.sh

    # Weekly
    claude --print -p "$(cat tasks/weekly-review.md)"

Both should print a path and a summary line to stdout, and leave a new
file in the project root.

---

## Scheduling — Linux / macOS (cron)

Open your crontab:

    crontab -e

Add these two lines, replacing `/abs/path/to/day-26-coach` with the real
absolute path:

    # Morning coaching, 8 AM daily
    0 8 * * * cd /abs/path/to/day-26-coach && tasks/run-morning-coaching.sh >> tasks/cron.log 2>&1

    # Weekly review, 6 PM every Sunday (DOW: 0 = Sunday)
    0 18 * * 0 cd /abs/path/to/day-26-coach && claude --print -p "$(cat tasks/weekly-review.md)" >> tasks/cron.log 2>&1

Cron runs with a minimal PATH, so if `claude` isn't found, use the
absolute path:

    which claude
    # /usr/local/bin/claude  →  use that in the cron lines

Verify with:

    crontab -l
    tail -f tasks/cron.log   # watch the next run land

---

## Scheduling — Windows (Task Scheduler)

The bash script also works on Windows via Git Bash (which ships with
Git for Windows). Path to bash is usually `C:\Program Files\Git\bin\bash.exe`.

Run this PowerShell **once**, as your user, to register both tasks:

```powershell
$proj = "C:\Users\Admin\Desktop\day-26-coach"
$bash = "C:\Program Files\Git\bin\bash.exe"

# --- Morning: 8 AM daily ---
$morningAction = New-ScheduledTaskAction `
    -Execute $bash `
    -Argument "tasks/run-morning-coaching.sh" `
    -WorkingDirectory $proj
$morningTrigger = New-ScheduledTaskTrigger -Daily -At 8am
Register-ScheduledTask `
    -TaskName "Coach-Morning" `
    -Action $morningAction `
    -Trigger $morningTrigger `
    -Description "Accountability Coach: morning nudges"

# --- Weekly: 6 PM Sunday ---
$weeklyAction = New-ScheduledTaskAction `
    -Execute $bash `
    -Argument "-c `"claude --print -p `"`"$(cat tasks/weekly-review.md)`"`"`"" `
    -WorkingDirectory $proj
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 6pm
Register-ScheduledTask `
    -TaskName "Coach-Weekly" `
    -Action $weeklyAction `
    -Trigger $weeklyTrigger `
    -Description "Accountability Coach: weekly deep review"
```

Inspect / test the registered tasks:

```powershell
Get-ScheduledTask -TaskName "Coach-*"
Start-ScheduledTask -TaskName "Coach-Morning"   # fires it now, useful for a smoke test
```

To remove later:

```powershell
Unregister-ScheduledTask -TaskName "Coach-Morning" -Confirm:$false
Unregister-ScheduledTask -TaskName "Coach-Weekly"  -Confirm:$false
```

If you'd rather avoid the embedded-quote dance for the weekly task,
copy `run-morning-coaching.sh` to `run-weekly-review.sh`, change the
last line to point at `tasks/weekly-review.md`, and use that script as
the `-Argument` for the weekly trigger — same pattern, no quoting
gymnastics.

---

## Why these run autonomously

Both briefs are read-only and have explicit "do not mutate the
database" constraints, so a misfire can't corrupt state — at worst, a
file gets written. Failures show up as either an empty/missing dated
file or a non-zero exit in the cron log; both are easy to spot the
next morning.
