#!/usr/bin/env bash
# hooks-compact A/B regression evaluator
#
# Usage:
#   ./eval/run-eval.sh                  # run all test cases
#   ./eval/run-eval.sh git-workflow     # run one test case
#   ./eval/run-eval.sh --list           # list available test cases
#
# Each test case runs two Amplifier sessions with the same prompt:
#   Session A  — WITH  hooks-compact (--bundle pointing to the behavior)
#   Session B  — WITHOUT hooks-compact (baseline, your normal bundle)
#
# After both sessions complete, analyze.sh is called to compare metrics
# and produce a PASS/FAIL verdict.
#
# Results are saved to eval/results/YYYY-MM-DD-HH-MM/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$SCRIPT_DIR/results/$(date +%Y-%m-%d-%H-%M)"
BUNDLE_URL="git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml"
FIXTURES_DIR="${HOOKS_COMPACT_EVAL_FIXTURES:-$SCRIPT_DIR/fixtures}"
TELEMETRY_DB="$HOME/.amplifier/hooks-compact/telemetry.db"
AMPLIFIER_PROJECTS="$HOME/.amplifier/projects"

mkdir -p "$RESULTS_DIR"

log() { echo "  $*"; }
header() { echo ""; echo "━━━ $* ━━━"; }

# ─────────────────────────────────────────────────────────────────────────────
# Session discovery helpers
# ─────────────────────────────────────────────────────────────────────────────

# Convert a filesystem path to the Amplifier project slug
# e.g. /Users/samule/repo/foo → -Users-samule-repo-foo
path_to_project_slug() {
  echo "${1//\//-}"
}

# List all UUID session IDs in a project's sessions dir (sorted)
list_sessions() {
  local project_slug="$1"
  local sessions_dir="$AMPLIFIER_PROJECTS/$project_slug/sessions"
  if [ ! -d "$sessions_dir" ]; then
    echo ""
    return
  fi
  find "$sessions_dir" -maxdepth 1 -type d \
    -name '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-*' \
    2>/dev/null | xargs -I{} basename {} | sort
}

# Return the session IDs that appeared after $BEFORE_IDS
new_sessions_since() {
  local project_slug="$1"
  local before_ids="$2"
  local after_ids
  after_ids=$(list_sessions "$project_slug")
  # comm -13: lines only in second input (new sessions)
  comm -13 <(echo "$before_ids" | sort) <(echo "$after_ids" | sort) | head -5
}

# ─────────────────────────────────────────────────────────────────────────────
# YAML parser helpers (Python3-based, no jq dependency)
# ─────────────────────────────────────────────────────────────────────────────

# Get all test case IDs
list_test_ids() {
  python3 - "$SCRIPT_DIR/test-cases.yaml" << 'PYEOF'
import sys, re
content = open(sys.argv[1]).read()
for m in re.finditer(r'^\s{2,4}-\s+id:\s+(\S+)', content, re.M):
    print(m.group(1))
PYEOF
}

# Get a specific field for a test case
get_case_field() {
  local test_id="$1"
  local field="$2"
  python3 - "$SCRIPT_DIR/test-cases.yaml" "$test_id" "$field" << 'PYEOF'
import sys, re

content = open(sys.argv[1]).read()
target_id = sys.argv[2]
field = sys.argv[3]

# Find the block for this test case
cases = re.split(r'(?=\s{2,4}-\s+id:)', content)
for block in cases:
    id_m = re.search(r'id:\s+(\S+)', block)
    if id_m and id_m.group(1) == target_id:
        m = re.search(rf'{re.escape(field)}:\s+"?([^\n"]+)"?', block)
        if m:
            print(m.group(1).strip())
        break
PYEOF
}

# ─────────────────────────────────────────────────────────────────────────────
# Run one test case (A/B sessions)
# ─────────────────────────────────────────────────────────────────────────────
run_test_case() {
  local test_id="$1"
  local prompt
  local working_dir
  prompt=$(get_case_field "$test_id" "prompt")
  working_dir=$(get_case_field "$test_id" "working_dir")
  # Resolve path tokens from test-cases.yaml
  working_dir="${working_dir/\$REPO_ROOT/$REPO_DIR}"
  working_dir="${working_dir/\$FIXTURES_DIR/$FIXTURES_DIR}"

  local project_slug
  project_slug=$(path_to_project_slug "$working_dir")

  header "Test case: $test_id"
  log "Working dir: $working_dir"
  log "Prompt:      ${prompt:0:80}..."
  echo ""

  # ── Session A: WITH hooks-compact ──
  log "▶  Session A — WITH hooks-compact"
  local before_a
  before_a=$(list_sessions "$project_slug")

  (cd "$working_dir" && \
    amplifier run \
      --bundle "$BUNDLE_URL" \
      --mode chat \
      "$prompt") || true

  local session_a
  session_a=$(new_sessions_since "$project_slug" "$before_a" | head -1)

  if [ -z "$session_a" ]; then
    log "ERROR: Could not find Session A (no new sessions in $working_dir)"
    echo "FAIL (session not found)" > "$RESULTS_DIR/${test_id}_verdict.txt"
    return 1
  fi
  log "   Session A ID: $session_a"
  echo "$session_a" > "$RESULTS_DIR/${test_id}_session_a.txt"

  sleep 2  # Small pause to ensure session dirs are clearly distinct

  # ── Session B: WITHOUT hooks-compact ──
  log "▶  Session B — WITHOUT hooks-compact (baseline)"
  local before_b
  before_b=$(list_sessions "$project_slug")

  (cd "$working_dir" && \
    amplifier run \
      --mode chat \
      "$prompt") || true

  local session_b
  session_b=$(new_sessions_since "$project_slug" "$before_b" | head -1)

  if [ -z "$session_b" ]; then
    log "ERROR: Could not find Session B"
    echo "FAIL (session not found)" > "$RESULTS_DIR/${test_id}_verdict.txt"
    return 1
  fi
  log "   Session B ID: $session_b"
  echo "$session_b" > "$RESULTS_DIR/${test_id}_session_b.txt"

  # ── Analyze ──
  echo ""
  log "▶  Analyzing..."
  "$SCRIPT_DIR/analyze.sh" \
    "$session_a" \
    "$session_b" \
    "$working_dir" \
    | tee "$RESULTS_DIR/${test_id}_analysis.txt"

  # Extract verdict
  grep -E '^VERDICT:' "$RESULTS_DIR/${test_id}_analysis.txt" \
    > "$RESULTS_DIR/${test_id}_verdict.txt" || true
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
case "${1:---all}" in
  --list)
    echo "Available test cases:"
    list_test_ids | while read -r id; do
      name=$(get_case_field "$id" "name")
      printf "  %-20s %s\n" "$id" "$name"
    done
    exit 0
    ;;
  --all|-a|all)
    echo "hooks-compact eval — running all test cases"
    echo "Results will be saved to: $RESULTS_DIR"
    PASS=0; FAIL=0
    while IFS= read -r test_id; do
      if run_test_case "$test_id"; then
        verdict=$(cat "$RESULTS_DIR/${test_id}_verdict.txt" 2>/dev/null || echo "UNKNOWN")
        if echo "$verdict" | grep -q "^VERDICT: PASS"; then
          PASS=$((PASS + 1))
        else
          FAIL=$((FAIL + 1))
        fi
      else
        FAIL=$((FAIL + 1))
      fi
    done < <(list_test_ids)

    header "SUMMARY"
    echo "  PASS: $PASS  FAIL: $FAIL"
    echo "  Results: $RESULTS_DIR"
    if [ $FAIL -gt 0 ]; then exit 1; fi
    ;;
  *)
    # Run single test case
    test_id="$1"
    if ! list_test_ids | grep -qx "$test_id"; then
      echo "ERROR: Unknown test case '$test_id'"
      echo ""
      echo "Available test cases:"
      list_test_ids
      exit 1
    fi
    echo "hooks-compact eval — test case: $test_id"
    echo "Results will be saved to: $RESULTS_DIR"
    run_test_case "$test_id"
    ;;
esac
