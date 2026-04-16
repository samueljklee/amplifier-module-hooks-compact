# hooks-compact

An [Amplifier](https://github.com/microsoft/amplifier) hook module that compresses bash tool output by 60–96% before it enters the LLM context window. Inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk).

**Why?** A typical AI coding session generates tens of thousands of tokens of raw bash output (`git status` boilerplate, test runner noise, compilation progress). With hooks-compact, the signal reaches the model and the noise doesn't.

> **Measured in live Amplifier A/B sessions (✓):** `git diff` 96.2% · `git status` 80.4% · `pytest` all-pass 99.9% · `pytest` failures 39.1%<sup>†</sup> · `ruff check` 83.4%<sup>‡</sup>
>
> **Measured in simulation against real command output (sim):** `cargo test` 96% · `cargo build` 85% clean / 42% with warnings · `cargo clippy` 57% · `npm test` 92% all-pass / 23% failures<sup>†</sup> · `docker build` 53% · `curl -v` 76%
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

Numbers marked ✓ are from live A/B sessions. Numbers marked (sim) are from simulation against real command output. All A/B tests show identical model turns with and without the hook.

| Command Pattern | Strategy | All-pass | With failures | Notes |
|----------------|----------|----------|---------------|-------|
| `git status` | Branch + file groups, strip hints, cap lists at 10 | **80%** ✓ | — | |
| `git diff` | Diffstat + first 8 changed lines per file (≤5 files) | **96%** ✓ | **96%** ✓ | |
| `git log` | One-line-per-commit format | ~0%<sup>†</sup> | — | |
| `git push` | Compact ref on success; preserve errors on failure | **92%** (sim) | **8%** (correct) | Errors always preserved |
| `git pull` | Branch refs + file counts; strip remote chatter | **66%** (sim) | — | |
| `git add` | Returns `"ok"` (no output on success) | 0% (empty) | — | |
| `git commit` | Hash+message + files changed; strip remote noise | ~3% (sim) | — | Already compact |
| `cargo test` | `"✓ N passed (Xs)"` on all-pass; full failure blocks with panics | **96%** (sim) | **47%** (sim) | Full panics preserved |
| `pytest` | Same asymmetric behavior | **99.9%** ✓ | **39%** ✓<sup>‡</sup> | Full tracebacks preserved |
| `npm test` (jest/vitest/mocha) | Auto-detected; Jest failures include Expected/Received details | **92%** (sim) | **23%** (sim) | Full error blocks preserved |
| `cargo build` | `"ok"` on success; errors + warning locations on failure | **85%** (sim) | **56%** (sim) | |
| `tsc` | Error-only; `"ok"` on clean; count summary on failure | **0%**<sup>§</sup> (sim) | ~−6%<sup>§</sup> (sim) | Adds count summary |
| `npm run build` | `"ok"` on success; error lines on failure | ~80% | — | |
| `cargo clippy` | Each dead-code warning listed separately; group by lint code | **57%** (sim) | — | All function names shown |
| `ruff check` | Group-by-rule; all unique descriptions per rule code | — | **83%** ✓<sup>¶</sup> | Every import name shown |
| `eslint` | Group-by-rule; passthrough for already-compact clean output | **0%**<sup>**</sup> (sim) | **68%** (sim) | |

<sup>†</sup> `git log --oneline` is already compact — minimal savings by design.

<sup>‡</sup> Failure case: full traceback + assertion messages preserved per failing test. Model has everything needed to fix the issues. Savings are lower by design.

<sup>§</sup> `tsc` with no errors outputs nothing; output is already minimal. Adding a count summary slightly increases size, but provides a useful `✗ 4 error(s)` summary.

<sup>¶</sup> All unique violation descriptions shown per rule code. E.g., `F401 (9×): \`os\` imported but unused | \`sys\` imported but unused | ...` — the model sees every specific import name.

<sup>**</sup> ESLint with no issues outputs `✔ 0 problems` (already compact, not expanded further).

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

| Command Pattern | Strategy | Savings |
|----------------|----------|---------|
| `make` | Strip `make[N]:` entering/leaving directory lines; `"make: ok"` on empty | ~27–94% |
| `docker build` | Strip BuildKit internal/cached/transfer lines; keep steps and final image | **53%** (sim) |
| `pip install` | Strip download progress bars; `"pip: ok"` when all already satisfied | 52–95% (sim) |
| `brew install` | Strip fetch/pour lines; short-circuit already-installed | 31–61% (sim) |
| `curl` (verbose) | Strip connection handshake, request/response headers; keep body | **76%** (sim) |

**Docker note**: Both legacy format (` ---> <hash>`, `Using cache`) and modern BuildKit format (` => [internal]`, ` => CACHED [N/M]`, ` => => transferring`) are handled.

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
┌─ hooks-compact ──────────────────────────────────────────────────────
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
└──────────────────────────────────────────────────────────────────────
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
