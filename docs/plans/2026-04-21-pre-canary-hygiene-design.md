# Pre-Canary Hygiene Pass — `amplifier-module-hooks-compact`

> **Date:** 2026-04-21
> **Author:** Sam S.
> **Status:** Draft — pending rollout cohort answers to open questions (see § Open Questions)
> **Branch:** `fix/pre-canary-hygiene`
> **Tag target:** `v0.1.0-canary.1` (annotated)

---

## Evidence Sources

All findings in this document are grounded in verified evidence from:

- **Foundation-expert sweep** — exhaustive codebase walk against README claims, DTU reports, and contract surfaces
- **Crusty-old-engineer sweep** — independent gap analysis of telemetry, documentation drift, and operational readiness
- **Core-expert + foundation-expert source-code walkthroughs** — tag pinning verification against `amplifier-module-resolution` and `amplifier_foundation` source
- **Ground-truth file reads** — every file path and line number cited was read directly from the repository at commit `0cf59d4`

## Attribution

The three telemetry additions (outcome logging, config hash, team-report.sh) were surfaced by the **sibling rollout session** driving the canary broadcast plan for `amplifier-module-hooks-compact`. These items directly materialize gaps that crusty-old-engineer independently flagged:

> "no denominator — only compressed events are logged. you cannot answer 'what % of eligible bash calls were affected?'"
> "no config fingerprint — whether override files were present"
> "no team-level report"

---

## Goal

Prepare `amplifier-module-hooks-compact` for opt-in broadcast to the internal team (Brian, Salil, peers) by fixing hygiene issues (doc drift, stale artifacts, weak telemetry, unproven pinning), upgrading telemetry to produce usable canary signal, and verifying everything via a 12-pass DTU matrix with PR staging.

## Background

`amplifier-module-hooks-compact` is a `tool:post` hook that compresses bash output by 37% (stdout) with 11% fewer turns, DTU-verified against a 30-scenario evaluation suite (2026-04-17 baseline report). The module is ready for internal team rollout as an opt-in canary — teammates install via `amplifier bundle add` and provide real-world signal before the hook graduates to inclusion in a public bundle (flighted off by default).

Before that rollout, two independent reviews (foundation-expert and crusty-old-engineer) surfaced hygiene issues across documentation accuracy, telemetry completeness, operational readiness, and version pinning. This design captures the full hygiene pass required to make the canary credible.

## Approach

**Three-category triage** (Blocker / Required / Nice-to-have), **four-phase execution** (docs-only → code+tests → eval+DTU → tag creation + verification), with **PR staging after two gating DTU passes** so Brian and Salil see the work mid-stream. Pinning (`@main` → `@v0.1.0-canary.1`) is done in Phase A; tag creation happens in Phase C.0 before DTU gates run.

---

## Implementation Note: `.gitignore` and `git rm` Targeting

> **⚠️ Critical for the implementer:** Item R4 calls for `git rm` of two specific stale design docs. Item R5 calls for `git rm` of one HTML file. The `.gitignore` additions for these removals **must target specific filenames**, not directory globs:
>
> ```gitignore
> # Stale design docs removed in pre-canary hygiene (R4)
> docs/plans/2026-04-15-hooks-compact-design.md
> docs/plans/2026-04-15-hooks-compact-implementation.md
>
> # Stale sales material removed in pre-canary hygiene (R5)
> docs/*.html
> ```
>
> Do **NOT** use `docs/plans/` or `docs/plans/*.md` as a gitignore pattern — that would catch this very plan file (`2026-04-21-pre-canary-hygiene-design.md`).
>
> Note: The current `.gitignore` has `docs/` on line 12, which broadly ignores the entire directory. Phase A must also replace that line with targeted ignores so that `docs/plans/2026-04-21-pre-canary-hygiene-design.md` (and future plan files) can be tracked.

---

## Section 1 — Hygiene Items

### 🔴 Blockers

Proposal won't land credibly without these.

| # | Item | File | Evidence |
|---|------|------|----------|
| B1 | `behaviors/compact.yaml` ships `debug: true` | `behaviors/compact.yaml:14` | Every bash call dumps 15-line debug panel to teammate UI |
| B2 | README claims "0 regressions" — contradicts DTU report showing 2 FAIL + 2 MARGINAL | `README.md:3` vs `eval/results/dtu-ab-test-report-2026-04-17.md:10-15,33` | Actual: 16 PASS, 2 MARGINAL (pip-install), 2 FAIL (eslint: 15 vs 9 turns — real 67%-more-turns regression) |
| B3 | Telemetry uses `uuid.uuid4()` not `coordinator.session_id` | `__init__.py:44` | `eval/analyze_ab.py:164-178` joins by session_id; mis-attributed telemetry makes canary signal unusable |
| B4 | `source: @main` everywhere — unpinned | `behaviors/compact.yaml:8`, `bundle.md:21,28,36`, `README.md:10,20,112` | Two teammates opting in at different times get different SHAs. Moving target theater. |

### 🟡 Required Before Canary Starts

| # | Item | File |
|---|------|------|
| R1 | `min_lines` drift: 5 (code) vs 20 (docs) | `behaviors/compact.yaml:11`, `hook.py:60`, `bundle.md:39`, `README.md:23,115` |
| R2 | README "no cap" vs `items[:50]` in lint filters | `README.md:69-71` vs `filters/lint.py:125,136,252,265,361,376` |
| R3 | `mount()` doesn't return unregister callable | `__init__.py:46-54` |
| R4 | `docs/plans/*.md` reference stale `data["tool_result"]` contract (code uses `data["result"]` — code is right) | `docs/plans/2026-04-15-hooks-compact-design.md:47-49,106-118`, `docs/plans/2026-04-15-hooks-compact-implementation.md:321,721,794-833` |
| R5 | `docs/hooks-compact-story.html` — stale sales material ("0 retries" claims, unpinned @main, stale test count 236 vs current 292) | `docs/hooks-compact-story.html:556,582,727,735,380,684,759` |
| R6 | `eval/` scripts not random-teammate runnable — hardcoded workstation paths, stderr suppressed via `2>/dev/null` | `eval/test-cases.yaml:17,28,39,50,83,96...`, `eval/simulate_all_filters.py:8-9,123-125,191-193`, `eval/run-eval.sh:125-130,150-154`, `eval/dtu-run-eval.sh:134-136,155-157` |
| R7 | `eval/simulate_all_filters.py:47-54` concatenates stdout+stderr but real hook only reads stdout — simulation tables overstate real behavior for stderr-heavy commands | `eval/simulate_all_filters.py:47-54` vs `hook.py:253-276` |
| R8 | Version quadruple-sourced: `pyproject.toml:3`, `bundle.md:4`, `behaviors/compact.yaml:3`, `__init__.py:20`. **Promoted from N1 because it touches `__init__.py` alongside B3 (session_id) — atomic with that fix.** Cost: ~10 lines + `scripts/bump-version.sh`. | `pyproject.toml:3`, `bundle.md:4`, `behaviors/compact.yaml:3`, `__init__.py:20` |
| R9 | No test for filter-raises-exception → passthrough path at `hook.py:294-309`. **Promoted from N4 because the fail-safe behavior is load-bearing for canary safety — untested critical code paths are exactly what canary signal should not depend on.** Cost: ~15 lines in `tests/test_hook.py`. | `hook.py:294-309`, `tests/test_hook.py` |

### 🟢 Nice-to-Have (Post-Canary)

| # | Item |
|---|------|
| N1 | Scenario count drift: README says "26 test cases", DTU report has 20, `./eval/run-eval.sh --list` shows 30 |
| N2 | README "cap lists at 10" for git-status; code caps at 50 (`filters/git.py:17` `_MAX_LIST_ITEMS = 50`) |

### Stdout-Only Blind Spot (Separate — Doc Fix Only)

Hook reads only `result.output.stdout` (`hook.py:253-276`). Commands writing primarily to stderr (`cargo build`, `cargo clippy`, `curl -v`) pass through unchanged. README line 13 currently claims "All bash output is now compressed automatically" — this is false.

**Decision:** Fix the claim, not the code. Defer real stderr-aware compression to v0.2.0.

---

## Section 2 — Fix Approach

### Phase A — Doc-Only Fixes

**B1 — Debug flag:**
- `behaviors/compact.yaml:14` → `debug: false`

**B2 — README accuracy:**
- `README.md:3` rewrite to match 2026-04-17 report: 16 PASS, 2 MARGINAL, 2 FAIL (not "0 regressions")
- Fix all README lines claiming "0/20 regressions"

**B4 — Pin all source refs:**
- Replace every `@main` with `@v0.1.0-canary.1` in `behaviors/compact.yaml:8`, `bundle.md:21,28,36`, `README.md:10,20,112`

**R1 — min_lines alignment:**
- `bundle.md:39` → `min_lines: 5` (matches code default and DTU-tested value)
- Check and fix `README.md:23,115` for stale `20` references

**R2 — Cap disclosure:**
- `README.md:69-71` → "cap at 50 per rule (safety valve)"
- `README.md:56` git-status → "cap at 50"

**R4 — Stale design docs:**
- `git rm docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md`
- Add those specific filenames to `.gitignore` (NOT a directory glob — see Implementation Note above)

**R5 — Stale sales material:**
- `git rm docs/hooks-compact-story.html`
- User moves local copy to `~/Downloads/Stories/`
- Add `docs/*.html` to `.gitignore`

**N1 — Scenario count accuracy:**
- Replace "26 test cases" with "30 eval scenarios defined; 20 DTU A/B verified; 10 simulation-only"

**N2 — Already covered by R2** (same README lines)

**Stdout blind spot — doc fix:**
- `README.md:13` rewrite to: *"Bash stdout is compressed automatically. Commands writing primarily to stderr (`cargo build`, `cargo clippy`, `curl -v`) pass through unchanged — known limitation tracked as v0.2.0 follow-up."*
- Open GitHub issue: "Hook v0.2: stderr-aware compression" linking to DTU report section 3

**.gitignore overhaul:**
- Replace the broad `docs/` entry (line 12) with targeted entries so that `docs/plans/` can contain tracked plan files:
  ```gitignore
  docs/plans/2026-04-15-hooks-compact-design.md
  docs/plans/2026-04-15-hooks-compact-implementation.md
  docs/*.html
  ```

### Phase B — Code Fixes with Unit Tests

**B3 — Session ID fix:**
- `__init__.py:44` → `session_id = coordinator.session_id`
- Drop `import uuid` from line 14

**R3 — Mount unregister callable:**
- Capture `coordinator.hooks.register(...)` return value; return it from `mount()`:
  ```python
  unregister = coordinator.hooks.register(
      "tool:post", hook.on_tool_post, priority=50, name=_MODULE_NAME,
  )
  return unregister
  ```

**R8 — Version single source of truth:**
- `_VERSION` via `importlib.metadata.version("amplifier-module-hooks-compact")` with `PackageNotFoundError` fallback to `"unknown"`
- Add `scripts/bump-version.sh` that updates `pyproject.toml`, `bundle.md`, `behaviors/compact.yaml` atomically

**R9 — Filter exception passthrough test:**
- Add `test_filter_exception_triggers_passthrough` to `tests/test_hook.py`
- Inject monkey-patched filter raising `RuntimeError("boom")`
- Assert hook returns `action="continue"`

**Telemetry: Outcome logging** (from sibling session):
- Add `outcome` column to `compression_log` table
- Valid values: `compressed`, `passthrough`, `no_match`, `filter_error`
- Log every **bash** `tool:post` invocation (not just compressed ones) to
  establish a denominator. Non-bash `tool:post` events skip telemetry
  entirely — the hook fast-exits in its classify step before reaching
  the logging path.
- Wrap all sqlite writes in try/except so DB errors never crash the hook (fail-safe)

**Telemetry: Config hash** (from sibling session):
- Add `config_hash` column to `compression_log` table
- Value: SHA-256 of the string concatenation of:
  1. Merged effective config dict, JSON-serialized with
     `json.dumps(config, sort_keys=True, separators=(",", ":"))` (canonical,
     deterministic across runs).
  2. Raw file bytes of any loaded user/project `output-filters.yaml` (hashed
     as-is; no YAML normalization — if bytes change, hash changes).
  3. Current `_VERSION` string.
- Concatenation order: config + YAML bytes + version. Separator: `\n---\n`
  between sections (so accidental overlap between sections cannot collide).
- Computed once at mount time; same hash on all rows in a session
- Edge case: if user edits `output-filters.yaml` mid-session, hash becomes stale — acceptable with documented "restart to pick up filter changes" note

**Telemetry: Schema migration:**
- On table init, check existing columns via `PRAGMA table_info(compression_log)`
- For each of `outcome TEXT` and `config_hash TEXT`: if column absent, run
  `ALTER TABLE compression_log ADD COLUMN {name} {type}`. If already present,
  skip (idempotent across mount cycles).
- Old rows retain NULL in new columns; queries must handle NULL gracefully
  (e.g., `WHERE outcome IS NOT NULL` or `COALESCE(outcome, 'legacy')`).
- No rollback path needed: `ADD COLUMN` with default NULL is strictly additive
  and reversible by dropping the column (SQLite 3.35+).
- Concrete pseudocode:
  ```python
  with sqlite3.connect(db_path) as conn:
      cursor = conn.execute("PRAGMA table_info(compression_log)")
      existing = {row[1] for row in cursor}
      for col, typ in [("outcome", "TEXT"), ("config_hash", "TEXT")]:
          if col not in existing:
              conn.execute(f"ALTER TABLE compression_log ADD COLUMN {col} {typ}")
      conn.commit()
  ```
- Wrap in try/except so migration failure never crashes the hook (fail-safe).

### Phase C — Eval Hygiene

**R6 — Eval portability:**
- Parameterize hardcoded paths via `HOOKS_COMPACT_EVAL_FIXTURES` env var or relative `./eval/fixtures/`
- Write `eval/bootstrap.sh` that creates `/tmp/test-*` fixtures from scratch
- Strip all `2>/dev/null` from `eval/run-eval.sh` and `eval/dtu-run-eval.sh` — fail loud

**R7 — Simulation honesty:**
- Change `eval/simulate_all_filters.py:47-54` to read only `stdout` (matching real hook)
- Expect simulation numbers for stderr-heavy commands to drop near 0% — this honesty is the point

**Telemetry: team-report.sh** (from sibling session):
- `scripts/team-report.sh` — bash + sqlite3 script generating markdown table for weekly cohort sharing
- Fields: command name (first token only), outcome, count, % of total, avg savings, date range
- **Strict privacy:** no paths, args, hostnames, or user identifiers
- Output pastable in channel

### Phase C.0 — Tag Creation (Pre-Gate)

Before Phase C.1 gates can run, the annotated tag must exist because Pass #4
resolves it. Create the tag on the feature branch HEAD (which at this point
is Commit 3):

```bash
git tag -a v0.1.0-canary.1 -m "First canary release of hooks-compact"
git push origin fix/pre-canary-hygiene
git push origin v0.1.0-canary.1
```

The tag points to a commit on the feature branch. It remains valid after
merge regardless of merge strategy (squash, rebase, or merge-commit) —
git tags are refs to SHAs, not to branch membership.

**Merge strategy note:** Prefer rebase-merge or merge-commit so that the
tag's commit ends up reachable from `main`. Squash-merge will leave the
tag pointing to an orphaned commit (still valid for `amplifier bundle add`
via the tag, but cosmetically detached from main history).

### Phase C.0a — DTU Codification Audit (Pre-Gate)

Before Phase C.1 gate #1 (all-30 baseline A/B) can run, the 10 simulation-only
scenarios must be codified as runnable DTU profiles. Compare `eval/test-cases.yaml`
(30 scenarios total) against the existing `eval/profiles/` directory; for any
scenario without a DTU profile, author one following the existing profile
template.

**Fallback if codification is not feasible within the hygiene pass scope:**
Scope Pass #1 to the 20 already-codified scenarios (matches 2026-04-17 baseline
exactly) and document in the README that 10 scenarios remain simulation-only.
Note: this fallback means the 10 uncodified scenarios will not gain DTU evidence
during the canary and must be addressed in v0.1.1 or later.

**Decision point:** The implementer chooses codification vs fallback based on
codification complexity. Document the decision in Commit 3's message.

---

## Section 3 — Execution Phases and Commit Structure

### Commit Structure (4 commits on `fix/pre-canary-hygiene` branch)

```
Commit 1 — docs: pre-canary hygiene fixes
  All Phase A items (README/bundle.md/behaviors drift, rm stale docs/plans,
  rm hooks-compact-story.html, stdout blind-spot disclosure, .gitignore updates).
  Note: URI pinning (@main → @v0.1.0-canary.1) happens here; the tag itself
  is created later in Phase C.0 on Commit 3's HEAD. This is safe because no
  consumer clones from the tag until after Phase C.0 runs.

Commit 2 — fix: telemetry completion + mount unregister + version SSoT
  All Phase B items (session_id, mount unregister, importlib.metadata,
  outcome column + 4-state logging, config_hash column, schema migration,
  filter-exception passthrough test)

Commit 3 — eval: make harness runnable + honest simulation + team report script
  All Phase C code items (parameterize paths, eval/bootstrap.sh,
  strip 2>/dev/null, simulate_all_filters.py stdout-only,
  scripts/team-report.sh)

Commit 4 — eval: post-hygiene DTU baseline report
  eval/results/dtu-ab-test-report-<date>.md (new 30-scenario run from
  DTU pass #1). README.md top-line claim updated to reference the new report.
```

### Recovery Protocol

If a DTU pass fails after the corresponding phase's unit tests passed:

- **Gate pass failure (#1 or #4):** amend the relevant commit on the feature
  branch; re-run both gates; do not open the PR until both are green.
- **Merge-blocker failure (#5, #6, #7, #8, #9, or #11):** amend the relevant
  commit via `git commit --amend` or add a fixup commit; push; post PR comment
  noting the fix; re-run only the failed pass.
- **Parallel-validation failure (#10, #12, or #2/#3):** fix in a follow-up
  commit before merge; document the fix in the PR description.

Do NOT introduce a new feature branch or a separate PR for the fix. Keep the
history on a single branch to preserve reviewer context.

### Definition of Done (Per Phase)

**Phase A (Commit 1):**
- `pytest tests/` green
- `grep -rn "debug: true\|0 regressions\|min_lines: 20\|no cap\|cap lists at 10\|26 test cases" README.md bundle.md behaviors/` returns zero hits
- `git ls-files docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md docs/hooks-compact-story.html` returns empty

**Phase B (Commit 2):**
- All unit tests green including `test_filter_exception_triggers_passthrough`
- `python -c "from amplifier_module_hooks_compact import _VERSION; print(_VERSION)"` prints `0.1.0` (not `unknown`)
- `grep -n "uuid.uuid4" amplifier_module_hooks_compact/__init__.py` returns empty
- Schema migration test passes on pre-populated old-schema DB

**Phase C (Commit 3):**
- `./eval/bootstrap.sh && ./eval/run-eval.sh --all` completes inside fresh DTU container with no workstation paths
- `simulate_all_filters.py` output shows stderr-heavy commands at ~0% savings

**Phase C.0 (Tag Creation — Pre-Gate):**
- `v0.1.0-canary.1` annotated tag created on feature branch HEAD and pushed
- Tag resolves via `git show v0.1.0-canary.1` (prerequisite for Pass #4)
- All `@main` refs already replaced with `@v0.1.0-canary.1` in Commit 1

---

## Tag Pinning Decision

### Decision: Annotated Tag `v0.1.0-canary.1`

Both core-expert and foundation-expert independently walked the source code to verify tag resolution works:

| Source file | What it does | Why tags work |
|-------------|-------------|---------------|
| `amplifier-module-resolution/src/amplifier_module_resolution/sources.py:154-159` | `rsplit("@", 1)` extracts ref | Zero validation on ref type — tag flows identically to branch |
| `amplifier_foundation/paths/resolution.py:15` | Regex `r"^(?P<path>[^@]+)(?:@(?P<ref>.+))?$"` | Ref-type-agnostic; ParsedURI docstring at line 44 explicitly documents `@v1.0.0` as valid |
| `amplifier_foundation/sources/git.py:198-200` | Passes ref to `git clone --depth 1 --branch <ref>` | Works for both branches and tags per git |
| `amplifier_foundation/sources/protocol.py:52-64` | `is_pinned` detection | `starts_with("v") and any(c.isdigit() for c in ref)` → `v0.1.0-canary.1` returns `is_pinned=True` → `amplifier update` correctly skips it |
| `test_sources.py:94-100` | Explicit test with `@v1.0.0` | Passes |

### Ecosystem Caveat

Foundation-expert searched exhaustively — every `bundle.md` in amplifier-foundation, attractor, recipes, rust-dev, python-dev, typescript-dev, superpowers, and skills uses `@main`. **Zero bundles use tag syntax in production.** The code path is tested in unit tests but not exercised by any shipped bundle. This is why DTU pass #4 (tag resolution cold-cache) is a PR gate.

### Why Annotated (Not Lightweight) Tags

`git clone --depth 1 --branch <tag>` has historical edge cases with lightweight tags on older git versions. Annotated is safer:

```bash
git tag -a v0.1.0-canary.1 -m "First canary release of hooks-compact"
git push origin v0.1.0-canary.1
```

---

## DTU Verification Matrix (12 Passes)

### Heavy Passes — Full A/B Runs (All 30 Scenarios)

| # | Dimension | Purpose | Model |
|---|-----------|---------|-------|
| 1 | **Baseline re-run** — Anthropic Sonnet, all codified scenarios (30 if Phase C.0a completed; 20 if fallback taken), A/B | Hygiene + telemetry changes introduced no regressions vs 2026-04-17 baseline | `critical-ops` orchestration; `claude-sonnet-4-5` scenarios |
| 2 | **Provider variance** — OpenAI or Google, same 30 scenarios, A/B | Cross-provider regressions (turn patterns differ; filter compression may land differently) | `critical-ops` orchestration |
| 3 | **OS variance** — Ubuntu 22.04 vs 24.04 on baseline scenarios | Runtime/environment regressions (sqlite, git, uv versions) | `critical-ops` orchestration |

### Light Passes — Targeted Checks

| # | Check | Pass Criteria | Model |
|---|-------|---------------|-------|
| 4 | **Tag resolution cold-cache** | `amplifier bundle add git+...@v0.1.0-canary.1#subdirectory=behaviors/compact.yaml --app` completes from empty cache, hook loads, fires on `ls` | `fast` |
| 5 | **Telemetry outcomes** | Run 4 deliberate scenarios hitting each of `compressed`/`passthrough`/`no_match`/`filter_error`; DB has one row per scenario with outcome column populated correctly | `coding` |
| 6 | **Config hash stability** | Session A default config vs session B with modified `~/.amplifier/output-filters.yaml`; same config → same hash, modified config → different hash; hash is same across all rows in a session | `coding` |
| 7 | **Schema migration** | Pre-populate DB with old schema (no outcome, no config_hash), mount new hook; `ALTER TABLE` runs cleanly, old rows NULL in new columns, new inserts populated | `coding` |
| 8 | **Fail-safe filter exception** | Inject monkey-patched filter raising `RuntimeError`; hook returns `continue`, user sees original output, row logged with `filter_error` outcome | `coding` |
| 9 | **Volume** | 100 bash calls in single session; no hook crash; hook processing p95 < 20ms per bash call (measured via timing harness in the DTU test); all 100 rows present in `compression_log`; no sqlite lock contention errors in logs | `fast` |
| 10 | **Stderr pass-through honesty** | `cargo build`, `cargo clippy`, `curl -v`; `compressed_chars == original_chars` (exactly equal; no mutation); `passthrough` outcome logged (not `compressed`) | `fast` |
| 11 | **team-report.sh output** | Run against populated DB; valid markdown, no paths/args/hostnames leaked, percentages sum cleanly | `fast` |
| 12 | **Non-bash tool:post** | Invoke `grep` or `read_file`; hook fast-exits before telemetry; verify `compression_log` contains **zero rows** for the session where the tool was not bash. Confirmed via `SELECT COUNT(*) FROM compression_log WHERE session_id = ? AND command NOT LIKE 'bash%'` returning 0. | `fast` |

---

## PR Staging Sequence

### Phase C.1 — PR Gate (Serial)

Duration: approximately 1–2 hours depending on model throughput, cold-cache
downloads, and tag-resolution latency. Based on 2026-04-17 baseline runtime
scaled to codified scenario count plus the cold-cache bundle-add test.

| Pass | Gate condition |
|------|---------------|
| #1 — Baseline A/B | Must pass — confirms no regression from hygiene + telemetry changes |
| #4 — Tag resolution cold-cache | Must pass — validates the unproven pinning mechanism |

Both green → `gh pr create --web` to open in browser.

### PR Creation

- Opens in browser so Sam, Brian, and Salil see progress mid-stream
- PR description references this design document and links to DTU pass #1 results

### Phase C.2 — Merge Blockers (Must All Pass Before Merge)

| Pass | What it validates |
|------|-------------------|
| #5 — Telemetry outcomes | New columns work — highest-risk new code |
| #7 — Schema migration | Upgrade path — blocks merge if users can't upgrade cleanly |
| #8 — Fail-safe filter exception | Correctness of the fail-safe path |
| #11 — team-report.sh privacy | Adversarial fixture: seed `compression_log` with rows containing known sensitive strings — `/Users/samule/secret-project`, `admin@example.com`, `SECRET_HOSTNAME_X9`, `--password=foobar`, `/home/real-user/.ssh/id_rsa`. Run `scripts/team-report.sh`. Capture output. Assert `grep -F` of each seed string returns **zero matches**. Also check for: paths (any `/Users/`, `/home/`, `/tmp/`), args (anything after command first token), hostnames, user identifiers (anything matching `[a-z]+@[a-z.]+` or `/home/[^/]+/`). |
| #6 — Config hash stability | Feature correctness |
| #9 — Volume | Performance under sustained use |

Six blocking passes (#5, #7, #8, #11, #6, #9). Each pass result posted as a PR comment with verdict.

### Phase C.3 — Canary Validation (Parallel with PR Review, Soft-Flag on Failure)

| Pass | What it validates |
|------|-------------------|
| #10 — Stderr honesty | Documentation claim matches actual behavior |
| #12 — Non-bash tool:post | No cross-tool interference |
| #2/#3 — Provider/OS variance | Run if cohort uses multiple providers/OSes |

Starts as soon as C.2 is green. Does not block merge. Decorates PR with additional evidence.

### Merge → Verify

1. All Phase C.2 passes green + PR approved → merge (prefer rebase-merge
   or merge-commit; see Phase C.0 note on squash-merge).
2. Verify the tag `v0.1.0-canary.1` is still valid post-merge:
   `git show v0.1.0-canary.1` succeeds.
3. Verify source URIs resolve end-to-end from a fresh shell (see
   Ready-for-Canary Checkpoint).

---

## Ready-for-Canary Checkpoint

Before telling Brian and Salil "opt in":

- [ ] All four commits merged to main
- [ ] `v0.1.0-canary.1` annotated tag exists and is pushed
- [ ] New DTU report checked in; ≥ 28/30 PASS (or ≥ 18/20 if Phase C.0a fallback taken); 0 net-new FAIL vs 2026-04-17 baseline
- [ ] README top-line claim matches the new report exactly
- [ ] `amplifier bundle add git+...@v0.1.0-canary.1#subdirectory=behaviors/compact.yaml --app` works end-to-end from a fresh shell
- [ ] `scripts/team-report.sh` produces privacy-clean output

---

## Stop/Rollback Conditions

- **Any heavy DTU pass FAIL with net-new regression vs baseline** → freeze, root-cause first, no tag
- **Phase C.2 check failure** → fix before merge
- **Phase C.3 check soft-flag** → document, proceed with note in PR

---

## Open Questions (For the Rollout Session to Answer)

1. **What providers does the canary cohort use?** Determines whether DTU pass #2 (provider variance) is required or can be cut.
2. **What OSes?** Determines whether DTU pass #3 (OS variance) is required or can be cut.
3. **Does any canary teammate run `amplifier-bundle-attractor` (which has `hooks-tool-truncation`)?** Determines whether a 13th coexistence check is needed — two hooks competing for the same `tool:post` event on bash output.
