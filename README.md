# hooks-compact

An [Amplifier](https://github.com/microsoft/amplifier) hook module that compresses bash tool output by 60–96% before it enters the LLM context window. Inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk).

**Why?** A typical AI coding session generates tens of thousands of tokens of raw bash output (`git status` boilerplate, test runner noise, compilation progress). With hooks-compact, the signal reaches the model and the noise doesn't.

> **Measured in live sessions:** `git diff` 96.2% · `git status` 80.4% · `pytest` (all pass) 99.9% · `pytest` (with failures) 39.1%<sup>†</sup> · `ruff check` 83.4%<sup>‡</sup>
>
> <sup>†</sup> Failure case: full error details preserved so the model has everything it needs to fix the issues.
> <sup>‡</sup> All unique violation descriptions shown per rule code — model sees every unused import name, every unused variable.

---

## Quick Start

One command to add hooks-compact to your app bundle:

```bash
amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml --app
```

That's it. All bash output is now compressed automatically.

### Alternative: Direct hook reference

If you want to customize configuration, add the hook directly in your bundle YAML:

```yaml
hooks:
  - module: hooks-compact
    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
    config:
      enabled: true
      min_lines: 5
      debug: false
```

---

## How It Works

Every `bash` tool result flows through a 4-stage pipeline:

1. **CLASSIFY** — match the command against registered filters (first match wins)
2. **PRE-PROCESS** — strip ANSI codes, collapse blank lines, truncate long lines
3. **FILTER** — apply command-specific compression (Python filter or YAML pipeline)
4. **DECIDE** — return `HookResult(action="modify")` with compressed output, or `continue` if no savings

**Fail-safe**: any error at any stage returns the raw output unchanged.

---

## Configuration Reference

```yaml
hooks:
  - module: hooks-compact
    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
    config:
      enabled: true           # set false to disable entirely
      min_lines: 5            # skip compression for output under N lines
      strip_ansi: true        # strip ANSI color codes before filtering
      show_savings: true      # show "compressed: X → Y chars (Z%)" info message
      debug: false            # show before/after comparison (for filter development)
      telemetry:
        local: true           # log compression stats to local SQLite (default on)
        remote: false         # remote telemetry (default off, requires consent)
        db_path: "~/.amplifier/hooks-compact/telemetry.db"
        retention_days: 90    # auto-prune records older than N days
```

---

## Built-in Filters

### Python Filters (complex, structured parsing)

Numbers marked ✓ are measured from live Amplifier sessions (A/B tested, model performance
verified). All-pass and failure cases are measured separately.

| Command Pattern | Strategy | All-pass | With failures |
|----------------|----------|----------|---------------|
| `git status` | Extract branch + file groups, strip hints, truncate large lists | **80%** ✓ | — |
| `git diff` | Diffstat + first 8 changed lines per file (≤5 files) | **96%** ✓ | **96%** ✓ |
| `git log` | One-line-per-commit format | 0–80%<sup>†</sup> | — |
| `git push/pull/add/commit` | `"ok"` on success, errors on failure | ~92% | — |
| `cargo test` | `"✓ N passed (Xs)"` on all-pass; failures only on partial | ~99% | ~60–80% |
| `pytest` | Same asymmetric behavior as cargo test | **99.9%** ✓ | **39%** ✓<sup>‡</sup> |
| `npm test` (jest/vitest/mocha) | Detected automatically, same pattern | ~85–99% | ~50–80% |
| `cargo build` | `"ok"` on success; errors + warnings on failure | ~90% | — |
| `tsc` | Error-only, strip success noise | ~85% | — |
| `npm run build` | Success short-circuit | ~80% | — |
| `cargo clippy` | Group-by-rule, deduplicate, count occurrences | — | ~80% |
| `ruff check` | Group-by-rule; all unique descriptions per rule code | — | **83%** ✓<sup>§</sup> |
| `eslint` | Same group-by-rule pattern | — | ~75% |

<sup>†</sup> `git log --oneline` is already compact — savings are minimal by design.

<sup>‡</sup> Failure case: full traceback + assertion messages preserved per failing test. Model
has everything needed to fix the issues. Savings are lower because error details are kept.

<sup>§</sup> Failure case: every unique violation description is shown per rule code. For example,
`F401 (9×): \`os\` imported but unused | \`sys\` imported but unused | ...` so the model sees
every specific import name, not just "9 F401 violations". Single-occurrence violations include
`file:line` location.

**Tool runner prefixes** are automatically stripped before matching, so all patterns work
whether the model uses the tool directly or via a package runner:

| Works natively | After prefix stripping |
|---------------|----------------------|
| `uvx ruff check` | → `ruff check` |
| `uv run pytest -v` | → `pytest -v` |
| `npx eslint src/` | → `eslint src/` |
| `bunx vitest run` | → `vitest run` |
| `poetry run pytest` | → `pytest` |
| `python -m pytest` | → `pytest` |
| `cd /path && uvx ruff` | → `ruff ...` |

### YAML Filters (declarative, regex pipelines)

| Command Pattern | Strategy |
|----------------|----------|
| `make` | Strip entering/leaving directory, `"make: ok"` on empty |
| `docker build` | Strip layer caching, keep final 20 lines |
| `pip install` | Strip download progress, cap at 30 lines |
| `brew install` | Strip fetch lines, short-circuit "already installed" |
| `curl` (verbose) | Strip connection handshake, keep response |

---

## Adding Custom YAML Filters

Create a YAML filter file at `.amplifier/output-filters.yaml` in your project (or `~/.amplifier/output-filters.yaml` for user-global):

```yaml
terraform-plan:
  match_command: "^terraform plan"
  strip_lines_matching:
    - "^\\s+#.*"           # resource attribute lines
    - "^Refreshing state"  # progress noise
  max_lines: 100
  on_empty: "terraform: no changes"

my-script:
  match_command: "^python scripts/migrate"
  strip_lines_matching:
    - "^DEBUG:"
    - "^\\[INFO\\] Processing"
  tail_lines: 20
```

**YAML pipeline stages** (run in strict order):

| Stage | Key | Description |
|-------|-----|-------------|
| 1 | `strip_lines_matching` | Remove lines matching any regex (mutually exclusive with `keep`) |
| 1 | `keep_lines_matching` | Keep only lines matching any regex |
| 2 | `replace` | Chainable list of `{pattern, replacement}` regex substitutions |
| 3 | `head_lines` / `tail_lines` | Keep first/last N lines |
| 4 | `max_lines` | Absolute cap (adds truncation marker) |
| 5 | `on_empty` | Fallback message when all lines are filtered out |

User filters have **higher priority** than built-in filters, so you can override any default.

---

## Debug Mode

Set `debug: true` to see exactly what's happening for every compression:

```
┌─ hooks-compact debug ──────────────────────────────────────────────────
│ Command:  cargo test
│ Filter:   cargo-test (Python)
│ Input:    4823 chars (262 lines)
│ Output:   11 chars (1 line)
│ Savings:  99.8%
│
│ ── ORIGINAL (first 20 lines) ──
│ warning: unused variable: `start`
│   --> src/init.rs:561:17
│ ...
│
│ ── COMPRESSED ──
│ ✓ 262 passed (0.08s)
└────────────────────────────────────────────────────────────────────────
```

Debug output goes to the user message only — **not injected into LLM context**.

---

## Telemetry

Local compression stats are stored in `~/.amplifier/hooks-compact/telemetry.db` (SQLite).
This is local-only — no data leaves your machine. You can disable it:

```yaml
telemetry:
  local: false
```

**What is stored:** command name (first token only, no args), filter used, character counts, savings percentage, and exit code. No command arguments, no output content, no file paths.

Query your stats:

```bash
sqlite3 ~/.amplifier/hooks-compact/telemetry.db \
  "SELECT command, filter_used, AVG(savings_pct) as avg, COUNT(*) as n
   FROM compression_log
   WHERE session_id NOT LIKE 'test%'
   GROUP BY command
   ORDER BY avg DESC"
```

---

## Regression Eval System

The `eval/` directory contains a regression harness to verify compression doesn't
hurt model performance when filters change:

```bash
# Run all test cases (A/B with and without the hook)
./eval/run-eval.sh

# Run a single test case
./eval/run-eval.sh git-workflow

# Analyze two existing sessions manually
./eval/analyze.sh <session-a-id> <session-b-id> /path/to/working-dir

# List available test cases
./eval/run-eval.sh --list
```

**PASS criteria**: Session A (with hook) must not make more than 1 extra bash tool call
vs Session B (without). This catches the key regression pattern — over-compression causing
the model to retry commands to get more context.

See [`eval/README.md`](eval/README.md) for full documentation.

---

## Attribution

Filter strategies and compression approaches are directly inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk) (MIT License). The innovation here is the Amplifier hook architecture (`tool:post` + `modify`) and user-extensible YAML filters.

---

## License

MIT — see [LICENSE](LICENSE).
