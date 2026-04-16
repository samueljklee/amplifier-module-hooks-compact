"""Unit tests for test runner output filters."""

from __future__ import annotations

from pathlib import Path


from amplifier_module_hooks_compact.filters.test_runners import (
    filter_cargo_test,
    filter_npm_test,
    filter_pytest,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── cargo test ────────────────────────────────────────────────────────────────


class TestFilterCargoTest:
    def test_all_pass_returns_single_line(self):
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 0)
        lines = [ln for ln in result.split("\n") if ln.strip()]
        assert len(lines) == 1

    def test_all_pass_has_tick(self):
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 0)
        assert "✓" in result

    def test_all_pass_shows_count(self):
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 0)
        assert "262 passed" in result

    def test_all_pass_shows_duration(self):
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 0)
        assert "0.08s" in result

    def test_all_pass_massive_savings(self):
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 0)
        # 262 test lines → 1 line: >95% savings
        assert len(result) < len(fixture) * 0.05

    def test_failures_shows_failure_count(self):
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 101)
        assert "2 failed" in result

    def test_failures_shows_passed_count(self):
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 101)
        assert "33 passed" in result

    def test_failures_shows_cross(self):
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 101)
        assert "✗" in result

    def test_failures_includes_failure_details(self):
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 101)
        # Failure output should contain test names or error messages
        assert (
            "auth" in result.lower()
            or "db" in result.lower()
            or "panicked" in result.lower()
        )

    def test_failures_shorter_than_original(self):
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        result = filter_cargo_test(fixture, "cargo test", 101)
        # Should be shorter (passing test lines removed)
        assert len(result) < len(fixture)

    def test_no_summary_returns_original(self):
        """When there's no recognizable summary, return as-is."""
        output = "some cargo output\nwithout standard format\n" * 5
        result = filter_cargo_test(output, "cargo test", 0)
        assert result == output

    def test_inline_summary(self):
        """Test with a simple inline cargo test output."""
        output = (
            "running 3 tests\n"
            "test a ... ok\n"
            "test b ... ok\n"
            "test c ... ok\n"
            "\n"
            "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.02s\n"
        )
        result = filter_cargo_test(output, "cargo test", 0)
        assert "3 passed" in result
        assert "✓" in result
        assert "0.02s" in result


# ── pytest ────────────────────────────────────────────────────────────────────


class TestFilterPytest:
    def test_all_pass_returns_short(self):
        fixture = (FIXTURES / "pytest_all_pass.txt").read_text()
        result = filter_pytest(fixture, "pytest", 0)
        lines = [ln for ln in result.split("\n") if ln.strip()]
        assert len(lines) == 1

    def test_all_pass_has_tick(self):
        fixture = (FIXTURES / "pytest_all_pass.txt").read_text()
        result = filter_pytest(fixture, "pytest", 0)
        assert "✓" in result

    def test_all_pass_shows_count(self):
        fixture = (FIXTURES / "pytest_all_pass.txt").read_text()
        result = filter_pytest(fixture, "pytest", 0)
        assert "89 passed" in result

    def test_all_pass_shows_duration(self):
        fixture = (FIXTURES / "pytest_all_pass.txt").read_text()
        result = filter_pytest(fixture, "pytest", 0)
        assert "1.23s" in result

    def test_failures_show_failure_details(self):
        fixture = (FIXTURES / "pytest_failures.txt").read_text()
        result = filter_pytest(fixture, "pytest", 1)
        # Should contain failure info
        assert "failed" in result.lower() or "FAILED" in result

    def test_failures_contains_test_names(self):
        fixture = (FIXTURES / "pytest_failures.txt").read_text()
        result = filter_pytest(fixture, "pytest", 1)
        # Should include the failing test info
        assert (
            "test_format_date_invalid" in result or "test_api_error_response" in result
        )

    def test_failures_shorter_than_original(self):
        fixture = (FIXTURES / "pytest_failures.txt").read_text()
        result = filter_pytest(fixture, "pytest", 1)
        assert len(result) < len(fixture)

    def test_inline_all_pass(self):
        output = (
            "============================= test session starts ==============================\n"
            "collected 5 items\n"
            "\n"
            "tests/test_foo.py .....                                              [100%]\n"
            "\n"
            "============================== 5 passed in 0.04s ==============================\n"
        )
        result = filter_pytest(output, "pytest tests/test_foo.py", 0)
        assert "5 passed" in result
        assert "✓" in result

    def test_inline_with_warnings(self):
        output = (
            "============================= test session starts ==============================\n"
            "collected 5 items\n"
            "\n"
            "tests/test_foo.py .....                                              [100%]\n"
            "\n"
            "============================== 5 passed, 2 warnings in 0.04s ==============================\n"
        )
        result = filter_pytest(output, "pytest", 0)
        assert "5 passed" in result

    # ── Quiet mode (-q) tests ─────────────────────────────────────────────────

    QUIET_ALL_PASS = (
        "........................................................................[  29%]\n"
        "........................................................................[  59%]\n"
        "........................................................................[  88%]\n"
        "...........................                                              [100%]\n"
        "243 passed in 0.39s\n"
    )

    QUIET_WITH_FAILURES = (
        "........F..                                                              [100%]\n"
        "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
        "1 failed, 10 passed in 0.12s\n"
    )

    def test_quiet_all_pass_compresses(self):
        """pytest -q all-pass output must be compressed even without === delimiters."""
        result = filter_pytest(self.QUIET_ALL_PASS, "uv run pytest -q", 0)
        assert "243 passed" in result, f"Expected count in result but got: {result!r}"
        assert result.count("\n") <= 1, f"Expected 1 line but got: {result!r}"

    def test_quiet_all_pass_has_tick(self):
        result = filter_pytest(self.QUIET_ALL_PASS, "uv run pytest -q", 0)
        assert "\u2713" in result, f"Expected tick in result but got: {result!r}"

    def test_quiet_all_pass_shorter_than_original(self):
        result = filter_pytest(self.QUIET_ALL_PASS, "uv run pytest -q", 0)
        assert len(result) < len(self.QUIET_ALL_PASS), (
            f"Expected compressed output shorter than {len(self.QUIET_ALL_PASS)} chars, "
            f"got {len(result)} chars"
        )


# ── npm test ──────────────────────────────────────────────────────────────────


class TestFilterNpmTest:
    def test_jest_all_pass(self):
        output = (
            "PASS src/auth.test.js\n"
            "PASS src/utils.test.js\n"
            "\n"
            "Test Suites: 2 passed, 2 total\n"
            "Tests:       15 passed, 15 total\n"
            "Snapshots:   0 total\n"
            "Time:        1.234 s\n"
            "Ran all test suites.\n"
        )
        result = filter_npm_test(output, "npm test", 0)
        assert "15 passed" in result or "✓" in result

    def test_jest_with_failures(self):
        output = (
            "PASS src/auth.test.js\n"
            "FAIL src/utils.test.js\n"
            "  ● test description\n"
            "    Expected: 'foo'\n"
            "    Received: 'bar'\n"
            "\n"
            "Test Suites: 1 failed, 1 passed, 2 total\n"
            "Tests:       1 failed, 14 passed, 15 total\n"
            "Time:        1.234 s\n"
        )
        result = filter_npm_test(output, "npm test", 1)
        assert "failed" in result.lower() or "✗" in result

    def test_mocha_all_pass(self):
        output = (
            "  auth\n    ✓ should login\n    ✓ should logout\n\n  2 passing (45ms)\n"
        )
        result = filter_npm_test(output, "npm test", 0)
        assert "2 passing" in result or "✓" in result

    def test_mocha_with_failures(self):
        output = (
            "  auth\n"
            "    ✓ should login\n"
            "    1) should logout\n"
            "\n"
            "  1 passing (45ms)\n"
            "  1 failing\n"
            "\n"
            "  1) auth should logout:\n"
            "     AssertionError: expected false to equal true\n"
        )
        result = filter_npm_test(output, "npm test", 1)
        assert "failing" in result.lower() or "1" in result
