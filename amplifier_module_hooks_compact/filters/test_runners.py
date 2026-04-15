"""Test runner output filters.

Implements RTK's key insight: asymmetric behavior based on test results.
- All pass  → one line summary (99% savings on the happy path)
- Some fail → failure details + summary, hide passing tests
- All fail  → all errors with context
"""

from __future__ import annotations

import re


# ── Cargo test ────────────────────────────────────────────────────────────────

# test result: ok. 262 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.08s
_CARGO_SUMMARY_RE = re.compile(
    r"test result: (ok|FAILED)\.\s+"
    r"(\d+) passed;\s+(\d+) failed.*?finished in ([\d.]+s)"
)

# test suite_name::test_name ... FAILED
_CARGO_FAILED_TEST_RE = re.compile(r"^test .+ \.\.\. FAILED")


def filter_cargo_test(output: str, command: str, exit_code: int | None) -> str:
    """Compress cargo test output.

    All pass  → "✓ N passed (Xs)"
    Some fail → failure details + "✗ N failed, M passed (Xs)"
    """
    m = _CARGO_SUMMARY_RE.search(output)
    if not m:
        # No recognizable summary line, return as-is
        return output

    status, passed, failed, duration = (
        m.group(1),
        int(m.group(2)),
        int(m.group(3)),
        m.group(4),
    )

    if status == "ok" and failed == 0:
        return f"✓ {passed} passed ({duration})"

    # Failures: extract failure blocks
    lines = output.split("\n")
    failure_lines: list[str] = []
    in_failures = False

    for line in lines:
        if line.strip() == "failures:":
            if not in_failures:
                in_failures = True
                continue
            else:
                # Second "failures:" block lists names only — skip
                in_failures = False
                continue
        if in_failures:
            failure_lines.append(line)
        # Keep "test result:" summary
        if line.startswith("test result:"):
            failure_lines.append(line)

    summary = f"✗ {failed} failed, {passed} passed ({duration})"
    if failure_lines:
        return summary + "\n" + "\n".join(failure_lines).strip()
    return summary


# ── pytest ────────────────────────────────────────────────────────────────────

# "89 passed in 1.23s" or "2 failed, 87 passed in 1.45s"
_PYTEST_SUMMARY_RE = re.compile(r"=+\s*(.*?(?:\d+ \w+.*?)) in ([\d.]+s)\s*=+")
# Line starting with "FAILED "
_PYTEST_FAILED_LINE_RE = re.compile(r"^FAILED ")
# Failure section header: "=== FAILURES ==="
_PYTEST_FAILURES_HEADER_RE = re.compile(r"^=+\s*FAILURES\s*=+")
# Short test summary: "=== short test summary info ==="
_PYTEST_SHORT_SUMMARY_RE = re.compile(r"^=+\s*short test summary info\s*=+")
# End section marker
_PYTEST_SECTION_END_RE = re.compile(r"^=+\s*\d+")


def filter_pytest(output: str, command: str, exit_code: int | None) -> str:
    """Compress pytest output.

    All pass  → "✓ N passed in Xs"
    Some fail → FAILURES section + short summary + result line
    """
    lines = output.split("\n")

    # Find the final summary line (last line matching the pytest result pattern)
    summary_line = ""
    for line in reversed(lines):
        if re.search(r"\d+ (passed|failed|error)", line) and "===" in line:
            summary_line = line.strip("= ").strip()
            break

    if not summary_line:
        return output

    # Check if all passed (no "failed" or "error" in summary)
    if not re.search(r"\d+ (failed|error)", summary_line):
        # Extract the clean summary
        m = re.search(r"(\d+ passed.*?) in ([\d.]+s)", summary_line)
        if m:
            return f"✓ {m.group(1)} in {m.group(2)}"
        return f"✓ {summary_line}"

    # Some failures: extract FAILURES section + short summary + final line
    result_sections: list[str] = []
    in_failures = False
    in_short_summary = False

    for line in lines:
        if _PYTEST_FAILURES_HEADER_RE.match(line):
            in_failures = True
            in_short_summary = False
            continue
        if _PYTEST_SHORT_SUMMARY_RE.match(line):
            in_short_summary = True
            in_failures = False
            result_sections.append("── short summary ──")
            continue
        if re.match(r"^=+\s*\d+", line) and not in_short_summary:
            in_failures = False
            # This is the final result line
            result_sections.append(line.strip("= ").strip())
            continue
        if in_failures or in_short_summary:
            result_sections.append(line)

    if result_sections:
        return "\n".join(result_sections).strip()
    return f"✗ {summary_line}"


# ── npm test / jest / vitest ──────────────────────────────────────────────────

_NPM_JEST_PASS_RE = re.compile(
    r"Tests?:\s+(\d+) passed,\s+(\d+) total|"
    r"Tests?:\s+(\d+) failed,.*?(\d+) total|"
    r"Test Suites?:.*?(\d+) passed"
)
_NPM_VITEST_SUMMARY_RE = re.compile(
    r"✓\s+(\d+) tests? passed"
    r"|(\d+) passed"
    r"|\s+(\d+) fail"
)


def filter_npm_test(output: str, command: str, exit_code: int | None) -> str:
    """Compress npm test / jest / vitest output.

    Detects the test framework from output patterns and applies
    appropriate compression.
    """
    # Try Jest format
    lines = output.split("\n")

    # Jest: look for "Tests: N passed, N total"
    jest_tests_line = ""
    jest_suites_line = ""
    for line in lines:
        if re.match(r"Tests?:\s+", line):
            jest_tests_line = line.strip()
        if re.match(r"Test Suites?:\s+", line):
            jest_suites_line = line.strip()

    if jest_tests_line:
        failed_m = re.search(r"(\d+) failed", jest_tests_line)
        passed_m = re.search(r"(\d+) passed", jest_tests_line)

        if failed_m and int(failed_m.group(1)) > 0:
            # Extract FAIL sections
            fail_lines = [
                line for line in lines if line.startswith("  ●") or "FAIL" in line
            ]
            summary = jest_tests_line
            if jest_suites_line:
                summary = jest_suites_line + "\n" + summary
            return (summary + "\n" + "\n".join(fail_lines[:30])).strip()
        elif passed_m:
            n = passed_m.group(1)
            # Try to get duration
            time_m = re.search(r"Time:\s+([\d.]+\s+\w+)", output)
            duration = time_m.group(1) if time_m else ""
            return f"✓ {n} passed{(' in ' + duration) if duration else ''}"

    # Vitest: look for summary block
    for line in lines:
        if re.search(r"✓\s+\d+", line) or re.search(r"Test Files\s+\d+ passed", line):
            passed = re.search(r"(\d+) passed", output)
            failed = re.search(r"(\d+) failed", output)
            duration = re.search(r"Duration\s+([\d.]+\w+)", output)
            if failed and int(failed.group(1)) > 0:
                return f"✗ {failed.group(1)} failed, {passed.group(1) if passed else 0} passed"
            if passed:
                dur = f" ({duration.group(1)})" if duration else ""
                return f"✓ {passed.group(1)} passed{dur}"

    # Mocha: look for "N passing" / "N failing"
    for line in lines:
        m = re.match(r"\s+(\d+) (passing|failing)", line)
        if m:
            n, result = m.group(1), m.group(2)
            if result == "passing":
                return f"✓ {n} passing"
            else:
                return f"✗ {n} failing"

    # Fallback: return last few lines
    non_empty = [ln for ln in lines if ln.strip()]
    return "\n".join(non_empty[-5:]) if non_empty else output
