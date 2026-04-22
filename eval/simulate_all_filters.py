#!/usr/bin/env python3
"""Comprehensive filter simulation script.

Tests all 26 filter scenarios with real command output (or realistic fixtures).
Reports before/after/savings in the standard table format.

Usage:
    uv run python eval/simulate_all_filters.py

Set HOOKS_COMPACT_EVAL_FIXTURES to override fixture directory (default: ./eval/fixtures).
"""

from __future__ import annotations

import subprocess
import sys
import os

# Add the module root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.environ.get(
    "HOOKS_COMPACT_EVAL_FIXTURES",
    os.path.join(REPO_ROOT, "eval", "fixtures"),
)

from amplifier_module_hooks_compact.filters.git import (
    filter_git_status,
    filter_git_diff,
    filter_git_log,
    filter_git_simple,
)
from amplifier_module_hooks_compact.filters.test_runners import (
    filter_cargo_test,
    filter_pytest,
    filter_npm_test,
)
from amplifier_module_hooks_compact.filters.build import (
    filter_cargo_build,
    filter_tsc,
    filter_npm_build,
)
from amplifier_module_hooks_compact.filters.lint import (
    filter_cargo_clippy,
    filter_ruff,
    filter_eslint,
)
from amplifier_module_hooks_compact.filters.yaml_engine import apply_yaml_filter
from amplifier_module_hooks_compact.hook import CompactHook
import yaml


def run_cmd(cmd: str, cwd: str | None = None, timeout: int = 30) -> tuple[str, int]:
    """Run a shell command and return (stdout_only, exit_code).

    Only stdout is returned — matching the real hook at hook.py:265-268
    which reads result.output.stdout exclusively.  Stderr-heavy commands
    (cargo build, cargo clippy, curl -v) will therefore show ~0% savings
    in simulation, which is the honest result (R7).
    """
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]", 1
    except Exception as e:
        return f"[error: {e}]", 1


def load_yaml_filter(name: str) -> dict:
    """Load a builtin YAML filter config."""
    filters_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "amplifier_module_hooks_compact",
        "builtin_filters",
    )
    with open(os.path.join(filters_dir, f"{name}.yaml")) as f:
        return yaml.safe_load(f)


def fmt_preview(text: str, max_chars: int = 80) -> str:
    """Format text for preview - first line + truncate."""
    if not text:
        return "(empty)"
    # Take first 80 chars of the first non-empty line
    first_line = text.strip().split("\n")[0]
    if len(first_line) > max_chars:
        return first_line[:max_chars] + "…"
    return first_line


def simulate(
    label: str,
    filter_name: str,
    raw_output: str,
    command: str,
    exit_code: int,
    filter_fn,
    is_yaml: bool = False,
) -> dict:
    """Run a simulation and return results."""
    if is_yaml:
        compressed = apply_yaml_filter(raw_output, filter_fn)
    else:
        compressed = filter_fn(raw_output, command, exit_code)

    input_chars = len(raw_output)
    output_chars = len(compressed)
    savings = 100.0 * (1 - output_chars / input_chars) if input_chars > 0 else 0.0

    return {
        "label": label,
        "filter_name": filter_name,
        "input_chars": input_chars,
        "output_chars": output_chars,
        "savings_pct": savings,
        "before_preview": fmt_preview(raw_output),
        "after_preview": fmt_preview(compressed),
        "before_full": raw_output,
        "after_full": compressed,
    }


def run_all_simulations() -> list[dict]:
    results = []

    print("Running simulations... (this may take a minute for Rust/Node projects)")

    # ── GIT FILTERS ───────────────────────────────────────────────────────────

    # 1. git status dirty
    output, code = run_cmd(
        "git status", cwd=REPO_ROOT
    )
    results.append(
        simulate(
            "git-status-dirty",
            "git-status",
            output,
            "git status",
            code,
            filter_git_status,
        )
    )

    # 2. git diff large (use the hooks-compact repo - it should have no changes, so simulate)
    # Use a realistic fixture
    git_diff_fixture = """\
diff --git a/amplifier_module_hooks_compact/hook.py b/amplifier_module_hooks_compact/hook.py
index 1234567..abcdefg 100644
--- a/amplifier_module_hooks_compact/hook.py
+++ b/amplifier_module_hooks_compact/hook.py
@@ -45,7 +45,12 @@ class CompactHook:
     def _classify_and_filter(self, output: str, command: str, exit_code: int | None) -> str | None:
         \"\"\"Classify command and apply appropriate filter.\"\"\"
-        result = self._registry.classify(command)
+        result = self._registry.classify(command)
+        if result is None:
+            # No filter matched - check for compound command
+            if '&&' in command or '; ' in command:
+                return None  # passthrough compound commands
+            return None
         if result is None:
             return None

diff --git a/amplifier_module_hooks_compact/pipeline.py b/amplifier_module_hooks_compact/pipeline.py
index 2345678..bcdefgh 100644
--- a/amplifier_module_hooks_compact/pipeline.py
+++ b/amplifier_module_hooks_compact/pipeline.py
@@ -12,6 +12,8 @@ _MAX_LINE_LENGTH = 500
+_MIN_LINES_DEFAULT = 5
+
 def strip_ansi(text: str) -> str:
     \"\"\"Remove ANSI escape codes from text.\"\"\"
-    return _ANSI_ESCAPE.sub('', text)
+    ansi_stripped = _ANSI_ESCAPE.sub('', text)
+    return ansi_stripped

diff --git a/README.md b/README.md
index 3456789..cdefghi 100644
--- a/README.md
+++ b/README.md
@@ -10,7 +10,7 @@
-**Tested savings: git status 80.4%, git diff 96.2%**
+**Tested savings: git status 80.4%, git diff 96.2%, pytest 99.9%**
"""
    results.append(
        simulate(
            "git-diff-large",
            "git-diff",
            git_diff_fixture,
            "git diff",
            0,
            filter_git_diff,
        )
    )

    # 3. git log
    output, code = run_cmd(
        "git log --oneline -10",
        cwd=REPO_ROOT,
    )
    results.append(
        simulate(
            "git-log",
            "git-log",
            output,
            "git log --oneline -10",
            code,
            filter_git_log,
        )
    )

    # 4. git push success (use "Everything up-to-date" simulation)
    git_push_output = """\
Enumerating objects: 5, done.
Counting objects: 100% (5/5), done.
Delta compression using up to 8 threads
Compressing objects: 100% (3/3), done.
Writing objects: 100% (3/3), 892 bytes | 892.00 KiB/s, done.
Total 3 (delta 2), reused 0 (delta 0), pack-reused 0
remote: Resolving deltas: 100% (2/2), completed with 2 local objects.
To github.com:samueljklee/amplifier-module-hooks-compact.git
   abc1234..def5678  main -> main
"""
    results.append(
        simulate(
            "git-push-success",
            "git-simple",
            git_push_output,
            "git push",
            0,
            filter_git_simple,
        )
    )

    # 5. git push rejected
    git_push_rejected = """\
To github.com:samueljklee/amplifier-module-hooks-compact.git
 ! [rejected]        main -> main (fetch first)
error: failed to push some refs to 'github.com:samueljklee/amplifier-module-hooks-compact.git'
hint: Updates were rejected because the remote contains work that you do not have locally.
hint: Integrate the remote changes (e.g. 'git pull ...') before pushing again.
hint: See the 'Note about fast-forwards' in 'git push --help' for details.
"""
    results.append(
        simulate(
            "git-push-rejected",
            "git-simple",
            git_push_rejected,
            "git push",
            1,
            filter_git_simple,
        )
    )

    # 6. git commit
    git_commit_output = "[main 4c32d28] fix: strip compound commands from filter matching\n 2 files changed, 18 insertions(+), 3 deletions(-)\n"
    results.append(
        simulate(
            "git-commit",
            "git-simple",
            git_commit_output,
            "git commit -m 'fix: ...'",
            0,
            filter_git_simple,
        )
    )

    # 7. git pull
    git_pull_output = """\
remote: Enumerating objects: 5, done.
remote: Counting objects: 100% (5/5), done.
remote: Compressing objects: 100% (3/3), done.
remote: Total 3 (delta 2), reused 0 (delta 0), pack-reused 0
Unpacking objects: 100% (3/3), 920 bytes | 920.00 KiB/s, done.
From github.com:samueljklee/amplifier-module-hooks-compact
   abc1234..def5678  main -> origin/main
Updating abc1234..def5678
Fast-forward
 amplifier_module_hooks_compact/hook.py | 5 +++++
 1 file changed, 5 insertions(+)
"""
    results.append(
        simulate(
            "git-pull",
            "git-simple",
            git_pull_output,
            "git pull",
            0,
            filter_git_simple,
        )
    )

    # ── TEST RUNNER FILTERS ────────────────────────────────────────────────────

    # 8. pytest all pass
    output, code = run_cmd(
        "uv run pytest -q",
        cwd=REPO_ROOT,
    )
    results.append(
        simulate(
            "pytest-all-pass",
            "pytest",
            output,
            "pytest -q",
            code,
            filter_pytest,
        )
    )

    # 9. pytest with failures
    output, code = run_cmd(
        f"uv run pytest {os.path.join(FIXTURES_DIR, 'test_eval_fail.py')} -v",
        cwd=REPO_ROOT,
    )
    results.append(
        simulate(
            "pytest-failures",
            "pytest",
            output,
            f"pytest -v {os.path.join(FIXTURES_DIR, 'test_eval_fail.py')}",
            code,
            filter_pytest,
        )
    )

    # 10. cargo test all pass
    output, code = run_cmd("cargo test", cwd=os.path.join(FIXTURES_DIR, "test-rust-project"))
    results.append(
        simulate(
            "cargo-test-pass",
            "cargo-test",
            output,
            "cargo test",
            code,
            filter_cargo_test,
        )
    )

    # 11. cargo test with failures
    output, code = run_cmd("cargo test", cwd=os.path.join(FIXTURES_DIR, "test-rust-fail"))
    results.append(
        simulate(
            "cargo-test-fail",
            "cargo-test",
            output,
            "cargo test",
            code,
            filter_cargo_test,
        )
    )

    # 12. npm test all pass
    output, code = run_cmd("npm test", cwd=os.path.join(FIXTURES_DIR, "test-node-project"))
    results.append(
        simulate(
            "npm-test-pass",
            "npm-test",
            output,
            "npm test",
            code,
            filter_npm_test,
        )
    )

    # 13. npm test with failures
    output, code = run_cmd("npm test", cwd=os.path.join(FIXTURES_DIR, "test-node-fail"))
    results.append(
        simulate(
            "npm-test-fail",
            "npm-test",
            output,
            "npm test",
            code,
            filter_npm_test,
        )
    )

    # ── LINT FILTERS ──────────────────────────────────────────────────────────

    # 14. ruff with errors
    output, code = run_cmd(
        f"uvx ruff check {os.path.join(FIXTURES_DIR, 'lint_issues.py')}",
        cwd=REPO_ROOT,
    )
    # Strip download noise from uvx
    lines = output.split("\n")
    cleaned = "\n".join(l for l in lines if not l.startswith("Downloading") and not l.startswith(" Downloading") and not l.startswith("Installed"))
    results.append(
        simulate(
            "ruff-errors",
            "ruff",
            cleaned.strip(),
            f"ruff check {os.path.join(FIXTURES_DIR, 'lint_issues.py')}",
            code,
            filter_ruff,
        )
    )

    # 15. ruff clean
    output, code = run_cmd(
        "uv run ruff check amplifier_module_hooks_compact/",
        cwd=REPO_ROOT,
    )
    results.append(
        simulate(
            "ruff-clean",
            "ruff",
            output,
            "ruff check amplifier_module_hooks_compact/",
            code,
            filter_ruff,
        )
    )

    # 16. cargo clippy
    output, code = run_cmd("cargo clippy", cwd=os.path.join(FIXTURES_DIR, "test-rust-clippy"))
    results.append(
        simulate(
            "cargo-clippy",
            "cargo-clippy",
            output,
            "cargo clippy",
            code,
            filter_cargo_clippy,
        )
    )

    # 17. eslint errors
    output, code = run_cmd("npx eslint src/", cwd=os.path.join(FIXTURES_DIR, "test-node-eslint"))
    results.append(
        simulate(
            "eslint-errors",
            "eslint",
            output,
            "eslint src/",
            code,
            filter_eslint,
        )
    )

    # ── BUILD FILTERS ─────────────────────────────────────────────────────────

    # 18. cargo build clean
    run_cmd("cargo clean", cwd=os.path.join(FIXTURES_DIR, "test-rust-project"))
    output, code = run_cmd("cargo build", cwd=os.path.join(FIXTURES_DIR, "test-rust-project"))
    results.append(
        simulate(
            "cargo-build-clean",
            "cargo-build",
            output,
            "cargo build",
            code,
            filter_cargo_build,
        )
    )

    # 19. cargo build with errors (create a file with errors)
    rust_err_dir = os.path.join(FIXTURES_DIR, "test-rust-errors")
    os.makedirs(rust_err_dir + "/src", exist_ok=True)
    with open(rust_err_dir + "/Cargo.toml", "w") as f:
        f.write('[package]\nname = "test_errors"\nversion = "0.1.0"\nedition = "2021"\n')
    with open(rust_err_dir + "/src/main.rs", "w") as f:
        f.write("""\
fn main() {
    let x: i32 = "not a number";
    let y = undefined_function();
    println!("{}", x);
}
""")
    output, code = run_cmd("cargo build", cwd=rust_err_dir)
    results.append(
        simulate(
            "cargo-build-errors",
            "cargo-build",
            output,
            "cargo build",
            code,
            filter_cargo_build,
        )
    )

    # 20. tsc errors
    ts_dir = os.path.join(FIXTURES_DIR, "test-ts-errors")
    os.makedirs(ts_dir, exist_ok=True)
    with open(ts_dir + "/tsconfig.json", "w") as f:
        f.write('{"compilerOptions": {"strict": true, "noEmit": true}}\n')
    with open(ts_dir + "/app.ts", "w") as f:
        f.write("""\
interface User {
    name: string;
    age: number;
}

function greet(user: User): string {
    return "Hello " + user.namee;  // typo: namee
}

const result: number = greet({name: "Alice", age: 30});  // wrong type
""")
    output, code = run_cmd("npx tsc --noEmit", cwd=ts_dir)
    # Use fixture if tsc isn't installed or the wrong tsc ran (npx intercept warning)
    tsc_not_real = (
        not output.strip()
        or "not the tsc command" in output
        or "not found" in output.lower()
        or code == 0 and not output.strip()
    )
    if tsc_not_real:
        # Realistic tsc output with 2 type errors
        output = """\
app.ts(8,30): error TS2551: Property 'namee' does not exist on type 'User'. Did you mean 'name'?
  Object literal may only specify known properties, and 'namee' does not exist in type 'User'.
app.ts(11,16): error TS2322: Type 'string' is not assignable to type 'number'.
  Type 'string' is not assignable to type 'number'.

Found 2 errors in 2 files.

Errors  Files
     1  app.ts:8
     1  app.ts:11
"""
        code = 1
    results.append(
        simulate(
            "tsc-errors",
            "tsc",
            output,
            "tsc --noEmit",
            code,
            filter_tsc,
        )
    )

    # 21. npm build success
    npm_build_output = """\
> test-node-project@1.0.0 build
> echo 'Build completed successfully'

Build completed successfully
"""
    results.append(
        simulate(
            "npm-build-success",
            "npm-build",
            npm_build_output,
            "npm run build",
            0,
            filter_npm_build,
        )
    )

    # ── YAML FILTERS ──────────────────────────────────────────────────────────

    # 22. pip install
    pip_cfg = load_yaml_filter("pip")
    pip_output = """\
Collecting requests
  Downloading requests-2.31.0-py3-none-any.whl (62 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.6/62.6 kB 2.4 MB/s eta 0:00:00
Collecting charset-normalizer<4,>=2 (from requests)
  Downloading charset_normalizer-3.3.2-cp311-cp311-macosx_11_0_arm64.whl (120 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 120.1/120.1 kB 5.2 MB/s eta 0:00:00
Collecting idna<4,>=2.5 (from requests)
  Downloading idna-3.6-py3-none-any.whl (61 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 61.6/61.6 kB 5.4 MB/s eta 0:00:00
Collecting urllib3<3,>=1.21.1 (from requests)
  Downloading urllib3-2.2.0-py3-none-any.whl (120 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 120.7/120.7 kB 5.1 MB/s eta 0:00:00
Collecting certifi>=2017.4.17 (from requests)
  Downloading certifi-2024.2.2-py3-none-any.whl (163 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 163.2/163.2 kB 5.6 MB/s eta 0:00:00
Installing collected packages: urllib3, idna, charset-normalizer, certifi, requests
Successfully installed certifi-2024.2.2 charset-normalizer-3.3.2 idna-3.6 requests-2.31.0 urllib3-2.2.0
"""
    results.append(
        simulate(
            "pip-install",
            "pip",
            pip_output,
            "pip install requests",
            0,
            pip_cfg,
            is_yaml=True,
        )
    )

    # 23. brew install (already installed)
    brew_cfg = load_yaml_filter("brew")
    brew_output = """\
Warning: jq 1.7.1 is already installed and up-to-date.
To reinstall 1.7.1, run:
  brew reinstall jq
"""
    results.append(
        simulate(
            "brew-already-installed",
            "brew",
            brew_output,
            "brew install jq",
            0,
            brew_cfg,
            is_yaml=True,
        )
    )

    # 24. make build
    make_cfg = load_yaml_filter("make")
    make_output, make_code = run_cmd("make all", cwd=os.path.join(FIXTURES_DIR, "test-make-project"))
    if not make_output.strip():
        make_output = "gcc -o hello hello.c\nBuild successful!\n"
    results.append(
        simulate(
            "make-build",
            "make",
            make_output,
            "make all",
            make_code,
            make_cfg,
            is_yaml=True,
        )
    )

    # 25. docker build (use fixture since Docker might not be available in all envs)
    docker_cfg = load_yaml_filter("docker")
    docker_output = """\
[+] Building 12.3s (8/8) FINISHED
 => [internal] load build definition from Dockerfile                       0.0s
 => => transferring dockerfile: 512B                                       0.0s
 => [internal] load .dockerignore                                          0.0s
 => => transferring context: 2B                                            0.0s
 => [internal] load metadata for docker.io/library/python:3.11-slim        1.2s
 => CACHED [1/4] FROM docker.io/library/python:3.11-slim@sha256:abc123     0.0s
 => [2/4] WORKDIR /app                                                     0.0s
 => [3/4] COPY requirements.txt .                                          0.0s
 => [4/4] RUN pip install -r requirements.txt                              8.1s
 => exporting to image                                                     0.9s
 => => exporting layers                                                    0.8s
 => => writing image sha256:def456abc789                                   0.0s
 => => naming to docker.io/library/myapp:latest                            0.0s
"""
    results.append(
        simulate(
            "docker-build",
            "docker",
            docker_output,
            "docker build .",
            0,
            docker_cfg,
            is_yaml=True,
        )
    )

    # 26. curl verbose
    curl_cfg = load_yaml_filter("curl")
    curl_output, curl_code = run_cmd("curl -v --max-time 5 https://example.com")
    if not curl_output.strip():
        curl_output = """\
  % Total    % Received % Xferd  Average Speed   Time
* Host example.com:443 was resolved.
*   Trying 93.184.216.34:443...
* Connected to example.com port 443
* SSL connection using TLSv1.3
* Server certificate: CN=example.com
> GET / HTTP/1.1
> Host: example.com
< HTTP/1.1 200 OK
< Content-Type: text/html; charset=UTF-8
< Content-Length: 1256
"""
    results.append(
        simulate(
            "curl-verbose",
            "curl",
            curl_output,
            "curl -v https://example.com",
            curl_code,
            curl_cfg,
            is_yaml=True,
        )
    )

    return results


def print_table(results: list[dict]) -> None:
    """Print results in the standard comparison table format."""
    print("\n" + "=" * 100)
    print("SIMULATION RESULTS: ALL 26 FILTER SCENARIOS")
    print("=" * 100)

    # Table header
    header = f"{'Scenario':<25} {'Filter':<15} {'Before':>8} {'After':>8} {'Savings':>8}  {'Before Preview':<40} {'After Preview':<40}"
    print(header)
    print("-" * 150)

    for r in results:
        savings_str = f"{r['savings_pct']:.1f}%"
        if r["savings_pct"] > 80:
            savings_marker = "✅"
        elif r["savings_pct"] > 40:
            savings_marker = "⚠️ "
        elif r["savings_pct"] > 0:
            savings_marker = "🔶"
        else:
            savings_marker = "➡️ "

        print(
            f"{r['label']:<25} {r['filter_name']:<15} {r['input_chars']:>8} {r['output_chars']:>8} {savings_str:>8} {savings_marker}  "
            f"{r['before_preview']:<40} {r['after_preview']:<40}"
        )

    print("\n")


def print_detail(results: list[dict]) -> None:
    """Print detailed before/after for each result."""
    print("\n" + "=" * 100)
    print("DETAILED BEFORE/AFTER FOR EACH SCENARIO")
    print("=" * 100)

    for r in results:
        savings_str = f"{r['savings_pct']:.1f}%"
        print(f"\n{'─' * 80}")
        print(f"SCENARIO: {r['label']} | Filter: {r['filter_name']} | Savings: {savings_str}")
        print(f"  Input: {r['input_chars']} chars | Output: {r['output_chars']} chars")
        print(f"{'─' * 80}")

        # Show BEFORE (first 10 lines)
        before_lines = r["before_full"].strip().split("\n")
        print("BEFORE (first 10 lines):")
        for line in before_lines[:10]:
            print(f"  {line}")
        if len(before_lines) > 10:
            print(f"  ... [{len(before_lines) - 10} more lines]")

        print()

        # Show AFTER (full)
        after_lines = r["after_full"].strip().split("\n")
        print("AFTER (full output):")
        for line in after_lines[:20]:
            print(f"  {line}")
        if len(after_lines) > 20:
            print(f"  ... [{len(after_lines) - 20} more lines]")


def check_broken_filters(results: list[dict]) -> list[str]:
    """Identify scenarios where the filter might be broken."""
    issues = []
    for r in results:
        # Flag scenarios where output is suspiciously short for a failure scenario
        if "fail" in r["label"] and r["output_chars"] < 50:
            issues.append(
                f"⚠️  {r['label']}: output only {r['output_chars']} chars - may be over-compressed!"
            )
        # Flag scenarios where filter produced nothing (empty output)
        if r["output_chars"] == 0:
            issues.append(f"❌ {r['label']}: filter produced EMPTY output - broken!")
        # Flag scenarios where compression made output LONGER
        if r["savings_pct"] < -10:
            issues.append(
                f"⚠️  {r['label']}: filter made output LONGER ({r['savings_pct']:.1f}%) - check filter"
            )
    return issues


if __name__ == "__main__":
    results = run_all_simulations()
    print_table(results)
    print_detail(results)

    issues = check_broken_filters(results)
    if issues:
        print("\n" + "=" * 80)
        print("⚠️  POTENTIAL ISSUES DETECTED:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✅ All filters look healthy - no obvious issues detected.")

    # Summary stats
    total_in = sum(r["input_chars"] for r in results)
    total_out = sum(r["output_chars"] for r in results)
    overall_savings = 100.0 * (1 - total_out / total_in) if total_in > 0 else 0
    print(f"\n📊 Overall: {total_in:,} → {total_out:,} chars ({overall_savings:.1f}% total savings across all scenarios)")
