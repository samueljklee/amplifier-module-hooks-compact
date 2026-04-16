#!/usr/bin/env bash
# Analyze two Amplifier session IDs and compare compression metrics.
#
# Usage:
#   ./eval/analyze.sh <session_a_id> <session_b_id> <working_dir>
#
# Session A = WITH hooks-compact
# Session B = WITHOUT hooks-compact (baseline)
#
# Exit code:
#   0 = PASS
#   1 = FAIL or error
#
# Output format:
#   Human-readable table + "VERDICT: PASS|FAIL" line at the end.

set -euo pipefail

SESSION_A="${1:-}"
SESSION_B="${2:-}"
WORKING_DIR="${3:-$PWD}"
TELEMETRY_DB="$HOME/.amplifier/hooks-compact/telemetry.db"
AMPLIFIER_PROJECTS="$HOME/.amplifier/projects"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$SESSION_A" ] || [ -z "$SESSION_B" ]; then
  echo "Usage: analyze.sh <session_a_id> <session_b_id> [working_dir]"
  exit 1
fi

# Convert working dir to project slug
PROJECT_SLUG="${WORKING_DIR//\//-}"
SESSIONS_DIR="$AMPLIFIER_PROJECTS/$PROJECT_SLUG/sessions"

SESSION_A_DIR="$SESSIONS_DIR/$SESSION_A"
SESSION_B_DIR="$SESSIONS_DIR/$SESSION_B"

if [ ! -d "$SESSION_A_DIR" ]; then
  echo "ERROR: Session A directory not found: $SESSION_A_DIR"
  exit 1
fi
if [ ! -d "$SESSION_B_DIR" ]; then
  echo "ERROR: Session B directory not found: $SESSION_B_DIR"
  exit 1
fi

# Delegate all metric extraction and comparison to the Python analyzer
python3 "$SCRIPT_DIR/analyze_sessions.py" \
  --session-a "$SESSION_A" \
  --session-b "$SESSION_B" \
  --session-a-dir "$SESSION_A_DIR" \
  --session-b-dir "$SESSION_B_DIR" \
  --telemetry-db "$TELEMETRY_DB"

# Exit code matches PASS/FAIL from the Python script
