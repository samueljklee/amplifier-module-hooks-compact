#!/usr/bin/env bash
# hooks-compact DTU A/B regression runner
#
# Runs all test cases from eval/test-cases.yaml inside two DTU containers:
#   Container A  -- WITH hooks-compact (passed as DTU_A_ID)
#   Container B  -- WITHOUT hooks-compact (passed as DTU_B_ID)
#
# Usage (called by the recipe, or directly):
#   ./eval/dtu-run-eval.sh <dtu-a-id> <dtu-b-id> <results-dir> <telemetry-db>
#
# Test cases with working_dir starting with /tmp/ use the same path inside the
# container. Test cases with working_dir in ~/repo/ are mapped to /root/hooks-compact/.
#
# Results saved per test case:
#   <results-dir>/<test-id>_session_a.txt     -- Session A UUID
#   <results-dir>/<test-id>_session_b.txt     -- Session B UUID
#   <results-dir>/<test-id>_analysis.txt      -- Full analysis report
#   <results-dir>/<test-id>_table_row.txt     -- One-line table row for aggregation
#   <results-dir>/<test-id>_verdict.txt       -- PASS or FAIL
#   <results-dir>/<test-id>_sessions_a/       -- Pulled session dir from Container A
#   <results-dir>/<test-id>_sessions_b/       -- Pulled session dir from Container B

set -euo pipefail

DTU_A_ID="${1:?Usage: dtu-run-eval.sh <dtu-a-id> <dtu-b-id> <results-dir> <telemetry-db>}"
DTU_B_ID="${2:?}"
RESULTS_DIR="${3:?}"
TELEMETRY_DB="${4:-$HOME/.amplifier/hooks-compact/telemetry.db}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="${HOOKS_COMPACT_EVAL_FIXTURES:-$SCRIPT_DIR/fixtures}"

mkdir -p "$RESULTS_DIR"

log() { echo "  $*"; }
header() { echo ""; echo "━━━ $* ━━━"; }

# ─── Helpers ──────────────────────────────────────────────────────────────────

# Map a local working_dir to its equivalent inside the DTU container
container_path() {
  local local_path="$1"
  # Local hooks-compact repo → /root/hooks-compact in container, preserving subpath
  if [[ "$local_path" == *"/amplifier-module-hooks-compact"* ]]; then
    local suffix="${local_path#*amplifier-module-hooks-compact}"
    echo "/root/hooks-compact${suffix}"
  else
    # /tmp/* stays as-is
    echo "$local_path"
  fi
}

# List session UUIDs inside a DTU container
list_container_sessions() {
  local dtu_id="$1"
  local project_path="$2"  # path inside container
  local project_slug="${project_path//\//-}"
  amplifier-digital-twin exec "$dtu_id" -- bash -c \
    "ls /root/.amplifier/projects/${project_slug}/sessions/ 2>/dev/null | sort" \
    2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('stdout', '').strip())
except:
    pass
" || true
}

# Discover new session in container (diff before/after)
new_session_in_container() {
  local dtu_id="$1"
  local project_path="$2"
  local before_sessions="$3"
  local after_sessions
  after_sessions=$(list_container_sessions "$dtu_id" "$project_path")
  # comm -13: lines only in second (new)
  comm -13 \
    <(echo "$before_sessions" | sort) \
    <(echo "$after_sessions" | sort) \
    | grep -E '^[0-9a-f]{8}-' | head -1 || true
}

# Get a test case field from test-cases.yaml
get_case_field() {
  local test_id="$1"
  local field="$2"
  python3 - "$SCRIPT_DIR/test-cases.yaml" "$test_id" "$field" << 'PYEOF'
import sys, re
content = open(sys.argv[1]).read()
target_id = sys.argv[2]
field = sys.argv[3]
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

# List all test case IDs
list_test_ids() {
  python3 - "$SCRIPT_DIR/test-cases.yaml" << 'PYEOF'
import sys, re
content = open(sys.argv[1]).read()
for m in re.finditer(r'^\s{2,4}-\s+id:\s+(\S+)', content, re.M):
    print(m.group(1))
PYEOF
}

# ─── Run one test case ─────────────────────────────────────────────────────────

run_test_case() {
  local test_id="$1"
  local prompt
  local working_dir
  local c_path
  prompt=$(get_case_field "$test_id" "prompt")
  working_dir=$(get_case_field "$test_id" "working_dir")
  # Resolve path tokens from test-cases.yaml
  working_dir="${working_dir/\$REPO_ROOT/$REPO_DIR}"
  working_dir="${working_dir/\$FIXTURES_DIR/$FIXTURES_DIR}"
  c_path=$(container_path "$working_dir")

  header "Test case: $test_id"
  log "Prompt: ${prompt:0:80}"
  log "Working dir (container): $c_path"
  echo ""

  # ── Session A: WITH hooks-compact ──────────────────────────────────────────
  log "▶ Session A — WITH hooks-compact (Container $DTU_A_ID)"
  local before_a
  before_a=$(list_container_sessions "$DTU_A_ID" "$c_path")

  amplifier-digital-twin exec "$DTU_A_ID" -- bash -c \
    "export PATH=/root/.local/bin:\$PATH && cd $c_path && amplifier run '$prompt'" \
    || true

  local session_a
  session_a=$(new_session_in_container "$DTU_A_ID" "$c_path" "$before_a")
  if [ -z "$session_a" ]; then
    log "ERROR: Could not find Session A"
    echo "FAIL (session not found)" > "$RESULTS_DIR/${test_id}_verdict.txt"
    return 1
  fi
  log "  Session A ID: $session_a"
  echo "$session_a" > "$RESULTS_DIR/${test_id}_session_a.txt"

  sleep 2

  # ── Session B: WITHOUT hooks-compact ──────────────────────────────────────
  log "▶ Session B — WITHOUT hooks-compact (Container $DTU_B_ID)"
  local before_b
  before_b=$(list_container_sessions "$DTU_B_ID" "$c_path")

  amplifier-digital-twin exec "$DTU_B_ID" -- bash -c \
    "export PATH=/root/.local/bin:\$PATH && cd $c_path && amplifier run '$prompt'" \
    || true

  local session_b
  session_b=$(new_session_in_container "$DTU_B_ID" "$c_path" "$before_b")
  if [ -z "$session_b" ]; then
    log "ERROR: Could not find Session B"
    echo "FAIL (session not found)" > "$RESULTS_DIR/${test_id}_verdict.txt"
    return 1
  fi
  log "  Session B ID: $session_b"
  echo "$session_b" > "$RESULTS_DIR/${test_id}_session_b.txt"

  # ── Pull session data ──────────────────────────────────────────────────────
  log "▶ Pulling session data..."
  local project_slug="${c_path//\//-}"
  local sessions_base="/root/.amplifier/projects/${project_slug}/sessions"
  local a_dir="$RESULTS_DIR/${test_id}_session_a"
  local b_dir="$RESULTS_DIR/${test_id}_session_b"
  mkdir -p "$a_dir" "$b_dir"

  for f in events.jsonl metadata.json transcript.jsonl; do
    incus file pull "${DTU_A_ID}${sessions_base}/${session_a}/$f" "$a_dir/$f" 2>/dev/null || true
  done
  for f in events.jsonl metadata.json transcript.jsonl; do
    incus file pull "${DTU_B_ID}${sessions_base}/${session_b}/$f" "$b_dir/$f" 2>/dev/null || true
  done

  # ── Pull telemetry from Container A ──────────────────────────────────────
  local tel_dir="$RESULTS_DIR/${test_id}_telemetry"
  mkdir -p "$tel_dir"
  incus file pull "${DTU_A_ID}/root/.amplifier/hooks-compact/telemetry.db" "$tel_dir/telemetry.db" 2>/dev/null || true

  local tel_db="$tel_dir/telemetry.db"
  [ -f "$tel_db" ] || tel_db="$TELEMETRY_DB"

  # ── Analyze ────────────────────────────────────────────────────────────────
  log "▶ Analyzing..."
  python3 "$SCRIPT_DIR/analyze_ab.py" \
    --scenario "$test_id" \
    --session-a "$session_a" \
    --session-b "$session_b" \
    --session-a-dir "$a_dir" \
    --session-b-dir "$b_dir" \
    --telemetry-db "$tel_db" \
    | tee "$RESULTS_DIR/${test_id}_analysis.txt"

  # Save table row separately for aggregation
  python3 "$SCRIPT_DIR/analyze_ab.py" \
    --scenario "$test_id" \
    --session-a "$session_a" \
    --session-b "$session_b" \
    --session-a-dir "$a_dir" \
    --session-b-dir "$b_dir" \
    --telemetry-db "$tel_db" \
    --table-only \
    > "$RESULTS_DIR/${test_id}_table_row.txt" 2>/dev/null || true

  # Extract verdict
  grep -E 'VERDICT: (PASS|FAIL)' "$RESULTS_DIR/${test_id}_analysis.txt" \
    | head -1 > "$RESULTS_DIR/${test_id}_verdict.txt" || true
}

# ─── Main ─────────────────────────────────────────────────────────────────────

header "hooks-compact DTU A/B Eval"
log "Container A (with):   $DTU_A_ID"
log "Container B (without): $DTU_B_ID"
log "Results dir:          $RESULTS_DIR"

PASS=0
FAIL=0
while IFS= read -r test_id; do
  if run_test_case "$test_id"; then
    verdict=$(cat "$RESULTS_DIR/${test_id}_verdict.txt" 2>/dev/null | grep -oE 'PASS|FAIL' || echo "UNKNOWN")
    if [ "$verdict" = "PASS" ]; then
      PASS=$((PASS + 1))
    else
      FAIL=$((FAIL + 1))
    fi
  else
    FAIL=$((FAIL + 1))
  fi
done < <(list_test_ids)

header "DTU EVAL SUMMARY"
log "PASS: $PASS   FAIL: $FAIL"
log "Results: $RESULTS_DIR"
if [ "$FAIL" -gt 0 ]; then exit 1; fi
