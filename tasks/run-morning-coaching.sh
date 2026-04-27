#!/usr/bin/env bash
# Run the morning coaching task autonomously via Claude Code.
# Cron-friendly: no TTY, no prompts, output goes to stdout.

set -euo pipefail

# Anchor to the project root regardless of where cron invokes us from.
cd "$(dirname "$0")/.."

# Hand the brief to Claude in print mode (single-shot, non-interactive).
exec claude --print -p "$(cat tasks/morning-coaching.md)"
