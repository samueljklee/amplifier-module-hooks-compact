# hooks-compact

An [Amplifier](https://github.com/microsoft/amplifier) hook module that compresses bash tool output by 60–90% before it enters the LLM context window. Inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk).

**Why?** A typical 30-minute AI coding session generates ~118,000 tokens of raw bash output (`git status` boilerplate, compilation progress, test runner noise). With hooks-compact, that drops to ~23,900 tokens — an **80% reduction** — without hiding anything that matters.

---

## Quick Start

One command to add hooks-compact to your app:

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
      min_lines: 20
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
      min_lines: 20           # skip compression for output under N lines
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

| Command Pattern | Strategy | Typical Savings |
|----------------|----------|----------------|
| `git status` | Extract branch + file groups, strip hints | 75% |
| `git diff` | Keep diffstat summary only | 75% |
| `git log` | One-line-per-commit format | 80% |
| `git push/pull/add/commit` | `"ok"` on success, errors on failure | 92% |
| `cargo test` | `"✓ N passed (Xs)"` on all-pass; failures only on partial | 90–99% |
| `pytest` | Same asymmetric behavior as cargo test | 90–99% |
| `npm test` (jest/vitest/mocha) | Detected automatically, same pattern | 85–99% |
| `cargo build` | `"ok"` on success; errors + warnings on failure | 85% |
| `tsc` | Error-only, strip success noise | 80% |
| `npm run build` | Success short-circuit | 80% |
| `cargo clippy` | Group-by-rule, deduplicate, count occurrences | 80% |
| `ruff check` | Same group-by-rule pattern | 80% |
| `eslint` | Same group-by-rule pattern | 75% |

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
┌─ hooks-compact debug ──────────────────────────────────────────────
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
└────────────────────────────────────────────────────────────────────
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

---

## Attribution

Filter strategies and compression approaches are directly inspired by [RTK (Rust Token Killer)](https://github.com/rtk-ai/rtk) (MIT License). The innovation here is the Amplifier hook architecture (`tool:post` + `modify`) and user-extensible YAML filters.

---

## License

MIT — see [LICENSE](LICENSE).
