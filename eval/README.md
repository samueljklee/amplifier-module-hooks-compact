# hooks-compact Eval System

A comprehensive A/B regression testing framework for the `hooks-compact` module.

## Overview

The eval system compares two Amplifier sessions for each test scenario:
- **Session A (with hook)**: `amplifier run --bundle <behavior-url>` — hooks-compact active
- **Session B (baseline)**: `amplifier run` — no compression, raw output

It measures:
1. **Compression quality** — input/output chars, savings %
2. **Model performance** — bash tool calls, LLM turns
3. **Regression signal** — did compression cause the model to retry commands?
4. **Qualitative notes** — did the model understand compressed output correctly?

**PASS criteria**: Session A makes ≤1 more bash calls than Session B. Regression = model
retrying commands due to insufficient compressed output.

---

## Quick Start

### Local A/B Test (single scenario)
```bash
./eval/run-eval.sh git-status-dirty
```

### Local A/B Test (all scenarios)
```bash
./eval/run-eval.sh --all
```

### DTU-based A/B Test (isolated containers)
```bash
# Launch two containers (with + without hooks-compact)
DTU_A=$(amplifier-digital-twin launch eval/profiles/hooks-compact-with.yaml | jq -r .id)
DTU_B=$(amplifier-digital-twin launch eval/profiles/hooks-compact-without.yaml | jq -r .id)

# Run all test cases
RESULTS="eval/results/$(date +%Y-%m-%d-%H-%M)-dtu"
mkdir -p "$RESULTS"
./eval/dtu-run-eval.sh "$DTU_A" "$DTU_B" "$RESULTS" ~/.amplifier/hooks-compact/telemetry.db

# Cleanup
amplifier-digital-twin destroy "$DTU_A"
amplifier-digital-twin destroy "$DTU_B"
```

### Analyze an existing session pair
```bash
python3 eval/analyze_ab.py \
  --scenario git-status-dirty \
  --session-a <uuid-a> \
  --session-b <uuid-b> \
  --session-a-dir ~/.amplifier/projects/<slug>/sessions/<uuid-a> \
  --session-b-dir ~/.amplifier/projects/<slug>/sessions/<uuid-b> \
  --telemetry-db ~/.amplifier/hooks-compact/telemetry.db
```

### Run the simulation (no API calls)
```bash
python3 eval/simulate_all_filters.py
```

---

## Files

| File | Purpose |
|------|---------|
| `test-cases.yaml` | 26 test cases across all filter categories |
| `run-eval.sh` | Local A/B runner (uses `amplifier run --bundle`) |
| `analyze.sh` | Analyze a specific session pair |
| `analyze_sessions.py` | Core metrics extraction from events.jsonl |
| `analyze_ab.py` | **NEW** — Improved analyzer with full table format + qualitative notes |
| `simulate_all_filters.py` | Run all 26 filters against real command output (no API) |
| `dtu-run-eval.sh` | **NEW** — DTU-based A/B runner using isolated containers |
| `profiles/hooks-compact-with.yaml` | **NEW** — DTU profile: Container A (hooks active) |
| `profiles/hooks-compact-without.yaml` | **NEW** — DTU profile: Container B (baseline) |
| `recipes/dtu-ab-test.yaml` | **NEW** — Recipe orchestrating full DTU A/B test cycle |

---

## Output Format

```
| Scenario                     | Input (chars) | Output (chars) |  Savings | With Turns | Without Turns | With Calls | Without Calls | Verdict |
| git-status-dirty             |           491 |            154 |    68.6% |          2 |             2 |          1 |             1 |    PASS |
```

The `analyze_ab.py` produces this exact table plus:
- Compression detail per command (from telemetry.db)
- Bash commands list for both sessions
- Token usage comparison
- Qualitative notes on model behavior
- PASS/FAIL verdict with reasoning

---

## Simulation Results (All 26 Scenarios)

Run with `python3 eval/simulate_all_filters.py`. Uses real command output from actual
projects. No API calls required.

| Scenario | Filter | Input (chars) | Output (chars) | Savings | Notes |
|----------|--------|--------------|----------------|---------|-------|
| git-status-dirty | git-status | 491 | 154 | **68.6%** | Live: 80.4% on larger dirty repos |
| git-diff-large | git-diff | 1,528 | 750 | **50.9%** | Live: 96.2% on 13KB diffs |
| git-log | git-log | 927 | 926 | ~0% | Already compact (--oneline) |
| git-push-success | git-simple | 424 | 30 | **92.9%** | Short-circuits to branch ref |
| git-push-rejected | git-simple | 449 | 387 | 13.8% | Error lines preserved (correct) |
| git-commit | git-simple | 116 | 114 | ~0% | Already minimal output |
| git-pull | git-simple | 475 | 132 | **72.2%** | Strips fetch noise |
| pytest-all-pass | pytest | 340 | 21 | **93.8%** | Live: 99.9% on 268 tests |
| pytest-failures | pytest | 2,332 | 1,337 | **42.7%** | Tracebacks preserved |
| cargo-test-pass | cargo-test | 611 | 18 | **97.1%** | → `✓ 4 passed (0.00s)` |
| cargo-test-fail | cargo-test | 1,127 | 674 | **40.2%** | Panic details preserved |
| npm-test-pass | npm-test | 227 | 11 | **95.2%** | → `✓ 4 passing` |
| npm-test-fail | npm-test | 801 | 700 | 12.6% | Mocha errors preserved |
| ruff-errors | ruff | 1,621 | 378 | **76.7%** | Live: 83.4% on 16 violations |
| ruff-clean | ruff | 19 | 19 | 0% | No violations = no compression (correct) |
| cargo-clippy | cargo-clippy | 849 | 272 | **68.0%** | Group-by-rule dedup |
| eslint-errors | eslint | 653 | 243 | **62.8%** | Group-by-rule dedup |
| cargo-build-clean | cargo-build | 138 | 20 | **85.5%** | → `ok (build succeeded)` |
| cargo-build-errors | cargo-build | 675 | 236 | **65.0%** | Error[E...] blocks preserved |
| tsc-errors | tsc | 401 | 188 | **53.1%** | Error lines extracted |
| npm-build-success | npm-build | 100 | 20 | **80.0%** | → `ok (build succeeded)` |
| pip-install | pip (YAML) | 1,091 | 391 | **64.2%** | Progress bars stripped |
| brew-already-installed | brew (YAML) | 100 | 88 | 12.0% | Small input, minimal savings |
| make-build | make (YAML) | 136 | 135 | ~0% | Simple Makefile, no noise to strip |
| docker-build | docker (YAML) | 1,074 | 434 | **59.6%** | CACHED/internal layers stripped |
| curl-verbose | curl (YAML) | 2,715 | 1,520 | **44.0%** | TLS handshake noise stripped |

### Key Design Principles
- **Asymmetric compression**: All-pass → aggressive summary; failures → preserve details
- **Fail-safe**: If filter errors, raw output passes through unchanged
- **Compound command guard**: `git status && git diff` passes through (avoids over-compression)
- **Shell prefix stripping**: `cd /path && git status` → strips `cd /path &&` before matching
- **Tool wrapper prefixes**: `uvx`, `uv run`, `npx`, `poetry run`, etc. stripped before matching

---

## Live A/B Test Results

Sessions from live Amplifier runs (not simulation):

| Scenario | Session A | Session B | Input (chars) | Output (chars) | Savings | With Turns | Without Turns | With Calls | Without Calls | Verdict | Qualitative |
|----------|-----------|-----------|--------------|----------------|---------|------------|---------------|------------|---------------|---------|-------------|
| git-workflow | 74bc5c12 | e3dd9207 | 16,637 | 1,835 | **89%** | 11 | 15 | 13 | 25 | **PASS** | Model used 12 fewer bash calls — more efficient with compressed output |
| pytest (all pass) | (session) | (session) | 23,038 | 21 | **99.9%** | 5 | 5 | 2 | 2 | **PASS** | Identical behavior |
| pytest (failures) | (session) | (session) | 2,520 | 1,527 | **39.1%** | 4 | 4 | 1 | 1 | **PASS** | Error details preserved, model correctly identified failures |
| ruff (errors) | (session) | (session) | 4,125 | 686 | **83.4%** | 5 | 5 | 2 | 2 | **PASS** | All rule violations visible |
| git (compound) | (session) | (session) | 972 | 972 | 0% | 4 | 4 | 1 | 1 | **PASS** | Correct passthrough of compound commands |

---

## DTU Setup

The DTU profiles provision full Amplifier environments for isolated A/B testing:

**`eval/profiles/hooks-compact-with.yaml`**:
- Ubuntu 24.04
- Amplifier installed
- hooks-compact in `bundle.app`
- Test fixtures pre-created (pytest fail file, Rust project, Node project)

**`eval/profiles/hooks-compact-without.yaml`**:
- Same setup WITHOUT hooks-compact
- Identical test fixtures for fair comparison

The DTU recipe (`eval/recipes/dtu-ab-test.yaml`) orchestrates the full lifecycle:
1. Validate DTU available
2. Create test fixtures
3. Launch both containers
4. Run all test cases in both
5. Pull session data
6. Analyze and report
7. Cleanup containers

---

## PASS/FAIL Criteria

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Extra bash calls | ≤ 1 | Over-compression causes retries |
| Extra turns | ≤ 2 | Excessive turns indicate confusion |
| Compression (all-pass) | ≥ 80% | Core value prop for successful runs |
| Compression (failures) | ≥ 0% | Error details must be preserved |

---

## Adding New Test Cases

1. Add to `test-cases.yaml` with id, prompt, working_dir, expected_commands
2. Create any needed fixtures in `/tmp/`
3. Run `python3 eval/simulate_all_filters.py` to verify filter output
4. Run `./eval/run-eval.sh <your-test-id>` for live A/B validation
