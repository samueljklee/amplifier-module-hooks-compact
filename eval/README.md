# hooks-compact Eval System

A regression test harness for verifying that `hooks-compact` compression improves token efficiency **without degrading model performance**.

## Problem It Solves

When you change a filter (e.g. tweak git-diff compression, add a new command), you want confidence that:
1. **Compression still works** — savings are measurable and meaningful
2. **Model still works** — same or fewer tool calls, no retries caused by garbled output

The eval system runs each test case as an A/B pair (with/without hook) and produces a verdict.

---

## Quick Start

```bash
# Run all test cases
./eval/run-eval.sh

# Run a single test case
./eval/run-eval.sh git-workflow

# List available test cases
./eval/run-eval.sh --list
```

Results are saved to `eval/results/YYYY-MM-DD-HH-MM/`.

---

## How It Works

For each test case:

1. **Session A (WITH hook)** — runs the prompt with `--bundle` pointing to `behaviors/compact.yaml`
2. **Session B (WITHOUT hook)** — runs the same prompt with your baseline bundle
3. **analyze.sh** compares the two sessions and produces a verdict

```
Test case: mixed-heavy
Working dir: /Users/samule/repo/amplifier-module-hooks-compact
Prompt:      review the project health...

▶  Session A — WITH hooks-compact
   Session A ID: abc12345-...

▶  Session B — WITHOUT hooks-compact (baseline)
   Session B ID: def67890-...

▶  Analyzing...
  ============================================================
    hooks-compact A/B Analysis
  ============================================================
    Session A (WITH hook):  abc12345-...
    Session B (WITHOUT):    def67890-...

    METRICS COMPARISON
    Metric                               Session A (hook)  Session B (base)
    ─────────────────────────────────────────────────────────────────────
    Bash tool calls                                     3                 3    0%
    Bash stdout (chars)                             1,835            16,637  −89%
    LLM input tokens                               12,450            18,200  −32%
    ...
    Compression events                                  3                 0

  ============================================================
    VERDICT: PASS
  ============================================================
```

---

## PASS/FAIL Criteria

| Check | PASS | FAIL |
|-------|------|------|
| **Tool call delta** | Session A tool calls ≤ Session B + 1 | Session A makes 2+ more bash calls |
| **Compression happened** | ≥1 telemetry event for compressed commands | — |

Additional informational metrics (not hard failures):
- LLM token comparison (informational — varies with model behavior)
- Stdout chars reduction (informational)

---

## Test Cases

| ID | Category | What It Tests |
|----|----------|---------------|
| `git-workflow` | git | git status + log + diff compression |
| `test-runner` | test-runner | pytest all-pass summary (99% savings) |
| `linter` | lint | ruff check group-by-rule dedup |
| `build-check` | build | python import check (short output) |
| `mixed-heavy` | mixed | all categories in one session |
| `short-output` | passthrough | below min_lines=5, should NOT compress |

---

## Manual Analysis

To analyze two sessions you already ran:

```bash
./eval/analyze.sh <session-a-id> <session-b-id> /path/to/working-dir
```

The Python analyzer (`analyze_sessions.py`) reads:
- `~/.amplifier/projects/<project>/sessions/<id>/events.jsonl` for each session
- `~/.amplifier/hooks-compact/telemetry.db` for compression events from Session A

---

## Adding Test Cases

Edit `eval/test-cases.yaml`:

```yaml
test_cases:
  - id: my-new-test
    name: "My new test case"
    category: git
    prompt: "exact prompt to send to the model"
    working_dir: /path/to/repo
    expected_commands: [git status]
    max_acceptable_tool_calls: 3
    max_retries: 0
```

---

## Results Directory

Results are saved to `eval/results/` (git-ignored). Each run creates:

```
eval/results/2026-04-16-14-30/
├── git-workflow_session_a.txt      # session A UUID
├── git-workflow_session_b.txt      # session B UUID
├── git-workflow_analysis.txt       # full analysis output
├── git-workflow_verdict.txt        # just the PASS/FAIL line
└── ...
```

---

## Running in CI

Add to your CI workflow when filter code changes:

```yaml
- name: Run hooks-compact regression eval
  run: |
    cd /path/to/working-dir
    ./eval/run-eval.sh all
```

The script exits with code 1 if any test case fails.
