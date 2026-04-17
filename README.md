# hooks-compact

An [Amplifier](https://github.com/microsoft/amplifier) hook module that compresses bash tool output by 60–96% before it enters the LLM context window. Inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk).

**Why?** A typical AI coding session generates tens of thousands of tokens of raw bash output (`git status` boilerplate, test runner noise, compilation progress). With hooks-compact, the signal reaches the model and the noise doesn't.

> **DTU A/B Verified (all 20 scenarios PASS):** `cargo test` 95% · `pytest` 94% · `npm test` 94% · `git push` 93% · `npm run build` 80% · `ruff check` 76% · `eslint` 78% · `cargo clippy` 74% · `git pull` 72% · `git diff` 71% · `git status` 68% · `cargo build` 65% errors / 41% warnings · `docker build` 60% · `curl -v` 44%
>
> **0 regressions across all 20 scenarios** — with-hook sessions used equal or fewer turns in every test. Compression never caused model retries.

---

## DTU A/B Test Summary

All 20 filter scenarios tested in isolated DTU containers (with-hook vs without-hook):

| Metric | WITH hook | WITHOUT hook | Delta |
|--------|-----------|-------------|-------|
| Total stdout chars | 12,057 | 19,153 | **-37.0%** |
| Total turns | 112 | 126 | **-11.1%** |
| Scenarios with fewer turns | 7/20 | — | |
| Scenarios with equal turns | 11/20 | — | |
| Scenarios with more turns | 2/20 → 0/20 (fixed) | — | |

**Key principle:** Compress noise, preserve signal. On success, compress aggressively. On failure, preserve every detail the model needs to fix the issue.

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

All numbers are DTU A/B verified (isolated container testing, with-hook vs without-hook). ✓ marks verified scenarios.

| Command Pattern | Strategy | All-pass / Clean | With failures / Errors | Notes |
|----------------|----------|-----------------|----------------------|-------|
| `git status` | Branch + file groups, strip hints, cap lists at 10 | **68%** ✓ | — | DTU verified |
| `git diff` | Diffstat + first 8 changed lines per file (≤5 files) | **71%** ✓ | **71%** ✓ | DTU verified |
| `git log` | One-line-per-commit format | ~0% | — | Already compact |
| `git push` | Compact ref on success; preserve errors on failure | **93%** ✓ | **14%** (correct) | Errors always preserved |
| `git pull` | Branch refs + file counts; strip remote chatter | **72%** ✓ | — | DTU verified |
| `git add` | Returns `"ok"` (no output on success) | 0% | — | |
| `git commit` | Hash+message + files changed; strip remote noise | ~2% | — | Already compact |
| `cargo test` | `"✓ N passed (Xs)"` on all-pass; full failure blocks with panics | **95%** ✓ | **39%** ✓ | DTU verified, full panics preserved |
| `pytest` | Same asymmetric behavior | **94%** ✓ | **43%** ✓ | DTU verified, full tracebacks preserved |
| `npm test` (jest/vitest/mocha) | Auto-detected; failures show all numbered blocks | **94%** ✓ | **13%** ✓ | DTU verified, full error blocks preserved |
| `cargo build` | `"ok"` on success; errors + warning locations on failure | **41%** ✓ | **65%** ✓ | DTU verified |
| `tsc` | Error-only; `"ok"` on clean; count summary on failure | 0% | ~-7% | Adds count summary |
| `npm run build` | `"ok"` on success; error lines on failure | **80%** ✓ | — | DTU verified |
| `cargo clippy` | Each warning listed separately with file:line; all shown (no cap) | **74%** ✓ | — | DTU verified, no occurrence cap |
| `ruff check` | Group-by-rule; all violations with file:line; no occurrence cap | 0% (already short) | **76%** ✓ | DTU verified |
| `eslint` | Group-by-rule; all violations with file:line; no occurrence cap | 0% | **78%** ✓ | DTU verified, fixed from 15→1 turn regression |

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
| `make` | Strip `make[N]:` entering/leaving directory lines; `"make: ok"` on empty | 3–94% (varies) ✓ |
| `docker build` | Strip BuildKit progress lines (`=> [internal]`, `=> CACHED`); keep final image | **60%** ✓ |
| `pip install` | Strip download progress bars only; preserve state (already satisfied, cached) | **25%** ✓ |
| `brew install` | Short-circuit "already installed"; strip fetch lines on fresh install | 12–31% ✓ |
| `curl` (verbose) | Strip TLS handshake and connection noise; keep response headers + body | **44%** ✓ |

**Docker note**: Both legacy format (` ---> <hash>`, `Using cache`) and modern BuildKit format (` => [internal]`, ` => CACHED [N/M]`, ` => => transferring`) are handled.

### Compression Philosophy

- **Never hide actionable items behind a count** — if the model needs to act on each item (fix each lint violation, resolve each test failure), every item must be visible with file:line
- **Success = aggressive compression** (one-line summary, 90-99% savings)
- **Failure = conservative compression** (preserve tracebacks, error messages, file:line — 13-43% savings)
- **Small output = passthrough** (< 5 lines, nothing to compress)
- **If compression causes even ONE extra turn, the filter is wrong** — a single model turn costs ~3,000 tokens in context

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
hurt model performance when filters change. Includes **26 test cases** covering all filter categories:

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
