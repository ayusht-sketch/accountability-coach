# Accountability Coach

A small Flask app that turns goals into a check-in habit. Set a goal, log
short check-ins with mood + progress, and get a tone-aware coaching
response (empathy / motivational / celebration / reengagement) plus a
streak calendar, milestone markers, and a mood timeline.

## Run locally

    pip install -r requirements.txt
    python app.py
    # open http://localhost:5000

The first boot seeds two sample goals + 10 check-ins so the dashboard
isn't empty.

## Run the test suite

    python test_app.py

30 tests across database, validation, coaching tones, edge cases, and
Flask routes.

## Production

`Procfile` runs gunicorn:

    web: gunicorn app:app --bind 0.0.0.0:$PORT

Optional env vars:

  - `COACH_SECRET` -- Flask session secret (set this in prod)
  - `PORT` -- bind port (the platform usually injects this)
