# Plan 1 — Doc Hygiene (Phase A) Implementation Plan

> **For execution:** Use `/execute-plan` mode or the subagent-driven-development recipe.
> **This is Plan 1 of 4.** See the design doc for the full pre-canary hygiene sweep.

**Goal:** Apply all Phase A doc-only fixes from the design document atomically as Commit 1 on branch `fix/pre-canary-hygiene`.

**Architecture:** Find-and-replace edits, file deletions, `.gitignore` overhaul, and one GitHub issue creation. TDD-shaped via pre-state / change / post-state `grep` assertions. No Python code changes, no test additions.

**Tech Stack:** Git, `edit_file`, `apply_patch`, `grep`, `gh` CLI.

**Design doc:** `docs/plans/2026-04-21-pre-canary-hygiene-design.md` (commit `8406d67`)

**Dependency:** None (this is the first plan in sequence).

**Next plan:** Plan 2 (Code + Telemetry) — depends on Plan 1 being merged or at least committed to the feature branch.

---

## Exploration Notes

These findings were verified during plan creation by reading every target file:

1. **Stale files are NOT git-tracked.** The current `.gitignore` line 12 has `docs/` which ignores the entire directory. The three stale files (`docs/plans/2026-04-15-*.md`, `docs/hooks-compact-story.html`) exist on disk but were never force-added to git. `git rm` will fail — use plain `rm` instead. The design doc at `docs/plans/2026-04-21-pre-canary-hygiene-design.md` WAS force-added (commit `27fe3b0`).
2. **README.md lines 23 and 115 already say `min_lines: 5`** — no change needed. Only `bundle.md:39` has the stale `min_lines: 20`.
3. **README.md line 71 (eslint row)** has Notes column "Fixed from 15→1 turn regression" — this contradicts the DTU report which shows eslint as ❌ FAIL (15 vs 9 turns). This is a false regression claim covered by B2 scope ("fix all lines claiming '0/20 regressions'") and will be corrected alongside the R2 cap changes on the same line.
4. **Seven `@main` occurrences** across 3 files: `behaviors/compact.yaml:8`, `bundle.md:21,28,36`, `README.md:10,20,112`.

---

## Task 1: Create Feature Branch

**Why:** All Plan 1 work goes on `fix/pre-canary-hygiene`, not `main`.

**Step 1: Verify clean working directory**

```bash
git status
```

Expected: `nothing to commit, working tree clean` on branch `main`.

**Step 2: Create and switch to feature branch**

```bash
git checkout -b fix/pre-canary-hygiene
```

Expected: `Switched to a new branch 'fix/pre-canary-hygiene'`

**Step 3: Verify branch**

```bash
git branch --show-current
```

Expected: `fix/pre-canary-hygiene`

---

## Task 2: B1 + B4 — Fix `behaviors/compact.yaml`

**Files:**
- Modify: `behaviors/compact.yaml` (lines 8 and 14)

**Why:** B1 — `debug: true` ships a 15-line debug panel to every teammate. B4 — `@main` is unpinned; two teammates installing at different times get different SHAs.

**Step 1: Verify pre-state**

```bash
grep -n "debug: true\|@main" behaviors/compact.yaml
```

Expected output (2 lines):
```
8:    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
14:      debug: true
```

**Step 2: Pin URI from `@main` to `@v0.1.0-canary.1` (line 8)**

Edit `behaviors/compact.yaml`:
- Old: `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main`
- New: `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1`

**Step 3: Fix debug flag (line 14)**

Edit `behaviors/compact.yaml`:
- Old: `      debug: true`
- New: `      debug: false`

**Step 4: Verify post-state**

```bash
grep -n "debug: true\|@main" behaviors/compact.yaml
```

Expected: **zero lines** (no output).

```bash
grep -n "debug: false" behaviors/compact.yaml
```

Expected: `14:      debug: false`

```bash
grep -n "@v0.1.0-canary.1" behaviors/compact.yaml
```

Expected: `8:    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1`

---

## Task 3: B4 + R1 — Fix `bundle.md`

**Files:**
- Modify: `bundle.md` (lines 21, 28, 36, 39)

**Why:** B4 — three `@main` URI references need pinning. R1 — `min_lines: 20` contradicts the code default of 5 and the DTU-tested value of 5.

**Step 1: Verify pre-state**

```bash
grep -n "@main\|min_lines: 20" bundle.md
```

Expected output (4 lines):
```
21:amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@main --app
28:  - bundle: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml
36:    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
39:      min_lines: 20        # skip compression for short output
```

**Step 2: Pin all three URIs (lines 21, 28, 36)**

Edit `bundle.md` — replace all occurrences of `@main` with `@v0.1.0-canary.1`:
- Old (line 21): `amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@main --app`
- New (line 21): `amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1 --app`

- Old (line 28): `  - bundle: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml`
- New (line 28): `  - bundle: git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1#subdirectory=behaviors/compact.yaml`

- Old (line 36): `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main`
- New (line 36): `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1`

**Step 3: Fix min_lines (line 39)**

Edit `bundle.md`:
- Old: `      min_lines: 20        # skip compression for short output`
- New: `      min_lines: 5         # skip compression for short output`

**Step 4: Verify post-state**

```bash
grep -n "@main\|min_lines: 20" bundle.md
```

Expected: **zero lines** (no output).

```bash
grep -c "@v0.1.0-canary.1" bundle.md
```

Expected: `3`

```bash
grep -n "min_lines: 5" bundle.md
```

Expected: `39:      min_lines: 5         # skip compression for short output`

---

## Task 4: B2 — Fix README.md Line 3 (False "0 Regressions" Claim)

**Files:**
- Modify: `README.md` (line 3)

**Why:** B2 — README claims "0 regressions" and "fixed to 0/20" but the DTU report (`eval/results/dtu-ab-test-report-2026-04-17.md`) shows 16 PASS, 2 MARGINAL, 2 FAIL.

**Step 1: Verify pre-state**

```bash
grep -n "0 regressions\|0/20" README.md
```

Expected output (1 line, with both patterns):
```
3:...with 0 regressions — compression never caused model retries. 7/20 scenarios used fewer turns, 11/20 used equal turns, and the 2 initial regressions were fixed to 0/20.
```

**Step 2: Rewrite line 3**

Edit `README.md`:
- Old: `An [Amplifier](https://github.com/microsoft/amplifier) hook module that compresses bash tool output by 60–96% before it enters the LLM context window. Across all 20 DTU-tested scenarios (isolated container A/B testing), hooks-compact delivers **37% stdout reduction** (12,057 vs 19,153 chars) and **11% fewer turns** (112 vs 126), with 0 regressions — compression never caused model retries. 7/20 scenarios used fewer turns, 11/20 used equal turns, and the 2 initial regressions were fixed to 0/20.`
- New: `An [Amplifier](https://github.com/microsoft/amplifier) hook module that compresses bash tool output by 60–96% before it enters the LLM context window. Across 20 DTU-tested scenarios (isolated container A/B testing), hooks-compact delivers **37% stdout reduction** (12,057 vs 19,153 chars) and **11% fewer turns** (112 vs 126) — **16 PASS**, **2 MARGINAL** (different model strategies, not compression-caused), **2 FAIL** (eslint: 15 vs 9 turns — under investigation). Full report: [`eval/results/dtu-ab-test-report-2026-04-17.md`](eval/results/dtu-ab-test-report-2026-04-17.md).`

**Step 3: Verify post-state**

```bash
grep -n "0 regressions\|0/20" README.md
```

Expected: **zero lines** (no output).

```bash
grep -n "16 PASS" README.md
```

Expected: `3:...— **16 PASS**, **2 MARGINAL**...`

---

## Task 5: Stdout Blind-Spot — Fix README.md Line 13

**Files:**
- Modify: `README.md` (line 13)

**Why:** README claims "All bash output is now compressed automatically" — this is false. The hook only reads `result.output.stdout`. Commands writing to stderr pass through unchanged.

**Step 1: Verify pre-state**

```bash
grep -n "All bash output is now compressed automatically" README.md
```

Expected:
```
13:That's it. All bash output is now compressed automatically.
```

**Step 2: Rewrite line 13 with stdout-only disclosure**

Edit `README.md`:
- Old: `That's it. All bash output is now compressed automatically.`
- New: `That's it. Bash stdout is compressed automatically. Commands writing primarily to stderr (`cargo build`, `cargo clippy`, `curl -v`) pass through unchanged — known limitation tracked as v0.2.0 follow-up.`

**Step 3: Verify post-state**

```bash
grep -n "All bash output is now compressed automatically" README.md
```

Expected: **zero lines** (no output).

```bash
grep -n "Bash stdout is compressed automatically" README.md
```

Expected: `13:...Bash stdout is compressed automatically. Commands writing primarily to stderr...`

---

## Task 6: B4 — Fix README.md URI Pins (Lines 10, 20, 112)

**Files:**
- Modify: `README.md` (lines 10, 20, 112)

**Why:** B4 — three `@main` references in README. All must become `@v0.1.0-canary.1`.

**Step 1: Verify pre-state**

```bash
grep -n "@main" README.md
```

Expected output (3 lines):
```
10:amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml --app
20:    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
112:    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main
```

**Step 2: Replace all three `@main` with `@v0.1.0-canary.1`**

Edit `README.md` — for each occurrence:
- Old (line 10): `amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@main#subdirectory=behaviors/compact.yaml --app`
- New (line 10): `amplifier bundle add git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1#subdirectory=behaviors/compact.yaml --app`

- Old (line 20): `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main`
- New (line 20): `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1`

- Old (line 112): `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@main`
- New (line 112): `    source: git+https://github.com/samueljklee/amplifier-module-hooks-compact@v0.1.0-canary.1`

> **Tip for the implementer:** You can use `replace_all` with the string `amplifier-module-hooks-compact@main` → `amplifier-module-hooks-compact@v0.1.0-canary.1` across `README.md` to hit all 3 in one operation. But verify the count afterwards.

**Step 3: Verify post-state**

```bash
grep -n "@main" README.md
```

Expected: **zero lines** (no output).

```bash
grep -c "@v0.1.0-canary.1" README.md
```

Expected: `3`

---

## Task 7: R2 + B2 — Fix README.md Filter Table (Lines 56, 69, 70, 71)

**Files:**
- Modify: `README.md` (lines 56, 69, 70, 71)

**Why:** R2 — code caps at 50 (`filters/git.py:17` `_MAX_LIST_ITEMS = 50`, similar in lint filters) but docs say "cap lists at 10" and "no cap" / "no occurrence cap". B2 — eslint Notes column falsely claims "Fixed from 15→1 turn regression" when the DTU report shows eslint as ❌ FAIL (15 vs 9 turns).

**Step 1: Verify pre-state**

```bash
grep -n "cap lists at 10\|no cap\|no occurrence cap\|Fixed from 15" README.md
```

Expected output (4 lines):
```
56:| `git status` | Branch + file groups, strip hints, cap lists at 10 | **68%** ✓ | — | DTU verified |
69:| `cargo clippy` | Each warning listed with file:line; all shown (no cap) | **74%** ✓ | — | No occurrence cap |
70:| `ruff check` | Group-by-rule; all violations with file:line; no occurrence cap | 0% (already short) | **76%** ✓ | DTU verified |
71:| `eslint` | Group-by-rule; all violations with file:line; no occurrence cap | 0% | **78%** ✓ | Fixed from 15→1 turn regression |
```

**Step 2: Fix line 56 (git-status cap)**

Edit `README.md`:
- Old: `| `git status` | Branch + file groups, strip hints, cap lists at 10 | **68%** ✓ | — | DTU verified |`
- New: `| `git status` | Branch + file groups, strip hints, cap at 50 | **68%** ✓ | — | DTU verified |`

**Step 3: Fix line 69 (cargo clippy cap)**

Edit `README.md`:
- Old: `| `cargo clippy` | Each warning listed with file:line; all shown (no cap) | **74%** ✓ | — | No occurrence cap |`
- New: `| `cargo clippy` | Each warning listed with file:line; cap at 50 per rule (safety valve) | **74%** ✓ | — | Cap at 50 per rule |`

**Step 4: Fix line 70 (ruff check cap)**

Edit `README.md`:
- Old: `| `ruff check` | Group-by-rule; all violations with file:line; no occurrence cap | 0% (already short) | **76%** ✓ | DTU verified |`
- New: `| `ruff check` | Group-by-rule; all violations with file:line; cap at 50 per rule (safety valve) | 0% (already short) | **76%** ✓ | DTU verified |`

**Step 5: Fix line 71 (eslint cap + false regression claim)**

Edit `README.md`:
- Old: `| `eslint` | Group-by-rule; all violations with file:line; no occurrence cap | 0% | **78%** ✓ | Fixed from 15→1 turn regression |`
- New: `| `eslint` | Group-by-rule; all violations with file:line; cap at 50 per rule (safety valve) | 0% | **78%** ✓ | ❌ FAIL: 15 vs 9 turns (under investigation) |`

**Step 6: Verify post-state**

```bash
grep -n "cap lists at 10\|no cap\|no occurrence cap" README.md
```

Expected: **zero lines** (no output).

```bash
grep -n "cap at 50" README.md
```

Expected output (4 lines):
```
56:...cap at 50...
69:...cap at 50 per rule (safety valve)...
70:...cap at 50 per rule (safety valve)...
71:...cap at 50 per rule (safety valve)...
```

```bash
grep -n "under investigation" README.md
```

Expected: `71:...❌ FAIL: 15 vs 9 turns (under investigation)...`

---

## Task 8: N1 — Fix README.md Scenario Count (Line 205)

**Files:**
- Modify: `README.md` (line 205)

**Why:** N1 — README says "26 test cases" but `eval/test-cases.yaml` defines 30 scenarios, of which 20 are DTU A/B verified and 10 are simulation-only.

**Step 1: Verify pre-state**

```bash
grep -n "26 test cases" README.md
```

Expected:
```
205:The `eval/` directory contains a regression harness to verify compression doesn't hurt model performance. Includes **26 test cases** covering all filter categories:
```

**Step 2: Fix scenario count**

Edit `README.md`:
- Old: `The `eval/` directory contains a regression harness to verify compression doesn't hurt model performance. Includes **26 test cases** covering all filter categories:`
- New: `The `eval/` directory contains a regression harness to verify compression doesn't hurt model performance. Includes **30 eval scenarios** (20 DTU A/B verified, 10 simulation-only) covering all filter categories:`

**Step 3: Verify post-state**

```bash
grep -n "26 test cases" README.md
```

Expected: **zero lines** (no output).

```bash
grep -n "30 eval scenarios" README.md
```

Expected: `205:...Includes **30 eval scenarios** (20 DTU A/B verified, 10 simulation-only)...`

---

## Task 9: `.gitignore` Overhaul

**Files:**
- Modify: `.gitignore` (line 12)

**Why:** The current `.gitignore` has `docs/` on line 12, which broadly ignores the entire `docs/` directory. This prevents new plan files (like this plan and the design doc) from being tracked without `git add -f`. Replace with targeted entries that block only the specific stale files.

**Step 1: Verify pre-state**

```bash
grep -n "^docs/" .gitignore
```

Expected:
```
12:docs/
```

```bash
git ls-files docs/
```

Expected: `docs/plans/2026-04-21-pre-canary-hygiene-design.md` (only file tracked under docs/, because it was force-added).

**Step 2: Replace broad `docs/` with targeted gitignore entries**

Edit `.gitignore` — replace line 12:
- Old: `docs/`
- New:
```
# Stale design docs removed in pre-canary hygiene (R4)
docs/plans/2026-04-15-hooks-compact-design.md
docs/plans/2026-04-15-hooks-compact-implementation.md

# Stale sales material removed in pre-canary hygiene (R5)
docs/*.html
```

**Step 3: Verify post-state**

```bash
grep -n "^docs/" .gitignore
```

Expected output (3 lines — the targeted entries, NOT `docs/`):
```
12:docs/plans/2026-04-15-hooks-compact-design.md
13:docs/plans/2026-04-15-hooks-compact-implementation.md
16:docs/*.html
```

```bash
grep -n "^docs/$" .gitignore
```

Expected: **zero lines** (the broad `docs/` is gone).

Verify that new plan files are now trackable:

```bash
git status --short docs/plans/2026-04-21-doc-hygiene-implementation.md 2>/dev/null || echo "File does not exist yet (expected at this point — it will be created by this plan)"
```

---

## Task 10: R4 — Delete Stale Design Docs

**Files:**
- Delete: `docs/plans/2026-04-15-hooks-compact-design.md`
- Delete: `docs/plans/2026-04-15-hooks-compact-implementation.md`

**Why:** R4 — these docs reference the stale `data["tool_result"]` contract (code uses `data["result"]`). They were never tracked by git (blocked by the old `docs/` gitignore), so we just delete them from disk.

> **Important:** These files are NOT tracked by git. Do NOT use `git rm` — it will fail with "pathspec did not match any files known to git". Use plain `rm`.

**Step 1: Verify files exist on disk**

```bash
ls -la docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md
```

Expected: both files listed with sizes (≈18KB and ≈41KB respectively).

**Step 2: Verify files are NOT tracked by git**

```bash
git ls-files docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md
```

Expected: **empty output** (no files listed — they were never tracked).

**Step 3: Delete the files**

```bash
rm docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md
```

**Step 4: Verify post-state**

```bash
ls docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md 2>&1
```

Expected: `No such file or directory` for both.

```bash
ls docs/plans/
```

Expected: only `2026-04-21-pre-canary-hygiene-design.md` remains (plus `2026-04-21-doc-hygiene-implementation.md` once this plan is committed).

---

## Task 11: R5 — Delete Stale HTML Sales Material

**Files:**
- Delete: `docs/hooks-compact-story.html`

**Why:** R5 — stale sales material with false claims ("0 retries", unpinned `@main`, stale test count 236 vs current 292).

> **🛑 STOP — User confirmation required.** The design document says the user manually moves this file to `~/Downloads/Stories/` BEFORE deletion. Verify this has been done. If the user has NOT copied it yet, do NOT delete. Instead, tell them:
> "The design doc says you move `docs/hooks-compact-story.html` to `~/Downloads/Stories/` before I delete it. Please do that first, then tell me to continue."

**Step 1: Check if user has already preserved the file**

```bash
ls ~/Downloads/Stories/hooks-compact-story.html 2>&1
```

If the file exists at `~/Downloads/Stories/`, continue. If not, **STOP and ask the user**.

**Step 2: Verify the source file exists on disk**

```bash
ls -la docs/hooks-compact-story.html
```

Expected: file listed (≈40KB).

**Step 3: Verify file is NOT tracked by git**

```bash
git ls-files docs/hooks-compact-story.html
```

Expected: **empty output** (not tracked — it was under the old `docs/` gitignore).

**Step 4: Delete the file**

```bash
rm docs/hooks-compact-story.html
```

**Step 5: Verify post-state**

```bash
ls docs/hooks-compact-story.html 2>&1
```

Expected: `No such file or directory`

---

## Task 12: GitHub Issue — stderr-Aware Compression

**Why:** The stdout blind-spot disclosure in Task 5 references "v0.2.0 follow-up." This issue tracks that follow-up work.

> **Note:** The command below is shown first so you can review it. If you prefer to create the issue via the GitHub web UI instead of `gh` CLI, that's fine — just make sure the title, body, and link match.

**Step 1: Verify `gh` CLI is authenticated**

```bash
gh auth status
```

Expected: shows authenticated to `github.com` as `samueljklee`.

**Step 2: Create the issue**

```bash
gh issue create \
  --repo samueljklee/amplifier-module-hooks-compact \
  --title "Hook v0.2: stderr-aware compression" \
  --body "## Summary

The hook currently reads only \`result.output.stdout\` (\`hook.py:253-276\`). Commands that write primarily to stderr (\`cargo build\`, \`cargo clippy\`, \`curl -v\`) pass through unchanged — 0% compression on stderr-heavy commands.

## Evidence

See \`eval/results/dtu-ab-test-report-2026-04-17.md\` — Section 3 (\"Stderr Blindspot\"):

> \`cargo build\`, \`cargo clippy\`, and \`curl -v\` output primarily to stderr, not stdout. The hook only compresses stdout. These commands show 0% compression because the hook never sees the output.

## Design Reference

\`docs/plans/2026-04-21-pre-canary-hygiene-design.md\` — Section 1, \"Stdout-Only Blind Spot (Separate — Doc Fix Only)\"

## Acceptance Criteria

- [ ] Hook reads both stdout and stderr from tool results
- [ ] Stderr-heavy commands (\`cargo build\`, \`cargo clippy\`, \`curl -v\`) show measurable compression
- [ ] DTU A/B verification with updated scenarios
- [ ] README updated to remove stdout-only limitation note"
```

**Step 3: Verify issue was created**

```bash
gh issue list --repo samueljklee/amplifier-module-hooks-compact --limit 1
```

Expected: shows the newly created issue "Hook v0.2: stderr-aware compression".

Record the issue number — you may want to reference it in the commit message or PR description.

---

## Task 13: Final Verification, Staging, and Commit

**Why:** All changes are atomic — one commit for all Phase A fixes. This task verifies everything, runs existing tests, stages, and commits.

**Step 1: Run the full DoD grep gauntlet**

This single command checks that ALL stale patterns are gone from the three edited files:

```bash
grep -rn "debug: true\|0 regressions\|0/20\|min_lines: 20\|no cap\|no occurrence cap\|cap lists at 10\|26 test cases\|@main\|All bash output is now compressed automatically" README.md bundle.md behaviors/compact.yaml
```

Expected: **zero lines** (no output). If ANY line appears, go back and fix the corresponding task.

**Step 2: Verify stale files are gone**

```bash
ls docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md docs/hooks-compact-story.html 2>&1
```

Expected: `No such file or directory` for all three.

**Step 3: Verify new plan files are trackable (not gitignored)**

```bash
git check-ignore docs/plans/2026-04-21-pre-canary-hygiene-design.md docs/plans/2026-04-21-doc-hygiene-implementation.md; echo "exit: $?"
```

Expected: **empty output** with `exit: 1` (meaning neither file is ignored — they CAN be tracked).

**Step 4: Verify stale filenames ARE still gitignored (belt-and-suspenders)**

```bash
git check-ignore docs/plans/2026-04-15-hooks-compact-design.md
```

Expected: `docs/plans/2026-04-15-hooks-compact-design.md` (confirming the targeted gitignore entry works).

**Step 5: Run existing tests to confirm no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all existing tests PASS. Phase A is doc-only — no test should break.

> **If any test fails:** STOP. Do not commit. The failure is unrelated to Plan 1 (we didn't touch any Python code). Investigate and fix the pre-existing failure before committing, or document it in the commit message.

**Step 6: Stage all changes**

```bash
git add behaviors/compact.yaml bundle.md README.md .gitignore
```

Also stage this plan file (if it exists on disk at this point):

```bash
git add docs/plans/2026-04-21-doc-hygiene-implementation.md 2>/dev/null || true
```

**Step 7: Review staged changes**

```bash
git diff --cached --stat
```

Expected: 4 files changed (`behaviors/compact.yaml`, `bundle.md`, `README.md`, `.gitignore`), plus optionally this plan file. No Python files. No test files.

```bash
git diff --cached
```

Review the full diff. Every change should match one of the tasks above. If you see anything unexpected, investigate before committing.

**Step 8: Commit**

```bash
git commit -m "docs: pre-canary hygiene fixes (Phase A)

- behaviors/compact.yaml: debug: true → false (B1)
- README.md: match DTU report (16/2/2, not \"0 regressions\") (B2)
- behaviors/compact.yaml, bundle.md, README.md: pin URIs to @v0.1.0-canary.1 (B4)
- bundle.md, README.md: min_lines: 5 (R1)
- README.md: \"cap at 50\" for clippy/ruff/eslint/git-status (R2, N3)
- rm docs/plans/2026-04-15-*.md (R4)
- rm docs/hooks-compact-story.html (R5)
- README.md: scenario counts 30/20/10 (N2)
- README.md: stdout-only disclosure + v0.2.0 follow-up note
- .gitignore: targeted entries, allow docs/plans/2026-04-21-* to be tracked

Refs: docs/plans/2026-04-21-pre-canary-hygiene-design.md"
```

**Step 9: Verify commit**

```bash
git log --oneline -1
```

Expected: shows the commit hash and message `docs: pre-canary hygiene fixes (Phase A)`.

Record the commit hash — Plan 2 depends on this commit existing on the branch.

---

## Definition of Done

- [ ] Branch `fix/pre-canary-hygiene` created from `main`
- [ ] `pytest tests/` green (no existing tests broken)
- [ ] `grep -rn "debug: true\|0 regressions\|min_lines: 20\|no cap\|cap lists at 10\|26 test cases\|@main" README.md bundle.md behaviors/` returns ZERO hits (check each pattern)
- [ ] `git ls-files docs/plans/2026-04-15-hooks-compact-design.md docs/plans/2026-04-15-hooks-compact-implementation.md docs/hooks-compact-story.html` returns empty
- [ ] `git ls-files docs/plans/2026-04-21-pre-canary-hygiene-design.md docs/plans/2026-04-21-doc-hygiene-implementation.md` returns both paths (confirming new `.gitignore` doesn't catch them)
- [ ] GitHub issue "Hook v0.2: stderr-aware compression" opened with link to DTU report
- [ ] One commit on `fix/pre-canary-hygiene` with the conventional commit message above
- [ ] Commit hash recorded in this plan document or PR description for reference
