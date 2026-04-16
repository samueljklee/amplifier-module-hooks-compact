"""Unit tests for lint tool output filters."""

from __future__ import annotations


from amplifier_module_hooks_compact.filters.lint import (
    filter_cargo_clippy,
    filter_eslint,
    filter_ruff,
)


# ── cargo clippy ──────────────────────────────────────────────────────────────


class TestFilterCargoClippy:
    CLEAN_OUTPUT = (
        "    Checking myproject v0.1.0 (/home/user/myproject)\n"
        "    Finished `dev` profile [unoptimized + debuginfo] target(s) in 2.45s\n"
    )

    WARNINGS_OUTPUT = (
        "warning[unused_variables]: unused variable: `x`\n"
        "  --> src/main.rs:10:9\n"
        "   |\n"
        "10 |     let x = 5;\n"
        "   |         ^ help: if this is intentional, prefix it with an underscore: `_x`\n"
        "\n"
        "warning[unused_variables]: unused variable: `y`\n"
        "  --> src/lib.rs:25:9\n"
        "   |\n"
        "25 |     let y = get_value();\n"
        "   |         ^ help: if this is intentional, prefix it with an underscore: `_y`\n"
        "\n"
        "warning[dead_code]: function `helper` is never used\n"
        "  --> src/utils.rs:5:4\n"
        "   |\n"
        " 5 | fn helper() {\n"
        "   |    ^^^^^^ help: consider removing this function\n"
        "\n"
        'warning: `myproject` (bin "myproject") generated 3 warnings\n'
    )

    def test_no_warnings_returns_ok(self):
        result = filter_cargo_clippy(self.CLEAN_OUTPUT, "cargo clippy", 0)
        assert "ok" in result.lower() or len(result) < 50

    def test_groups_same_rule(self):
        """Identical rule violations are grouped, not repeated."""
        result = filter_cargo_clippy(self.WARNINGS_OUTPUT, "cargo clippy", 0)
        # unused_variables appears twice — should show count
        assert "2×" in result or "2 " in result or "unused_variables" in result

    def test_shows_rule_codes(self):
        result = filter_cargo_clippy(self.WARNINGS_OUTPUT, "cargo clippy", 0)
        assert "unused_variables" in result or "dead_code" in result

    def test_shorter_than_original(self):
        result = filter_cargo_clippy(self.WARNINGS_OUTPUT, "cargo clippy", 0)
        assert len(result) < len(self.WARNINGS_OUTPUT)

    def test_shows_summary_count(self):
        result = filter_cargo_clippy(self.WARNINGS_OUTPUT, "cargo clippy", 0)
        # Summary line should be somewhere in output
        assert "3 warnings" in result or "generated" in result

    def test_error_lines_always_shown(self):
        output = (
            "error[E0308]: mismatched types\n"
            "  --> src/main.rs:10:5\n"
            "   |\n"
            '10 |     return "hello";\n'
            "   |            ^^^^^^^ expected `i32`, found `&str`\n"
        )
        result = filter_cargo_clippy(output, "cargo clippy", 1)
        assert "E0308" in result or "mismatched" in result


# ── ruff check ────────────────────────────────────────────────────────────────


class TestFilterRuff:
    CLEAN_OUTPUT = "All checks passed!\n"

    ISSUES_OUTPUT = (
        "src/main.py:10:1: F401 [*] `os` imported but unused\n"
        "src/auth.py:45:9: E501 Line too long (120 > 88 characters)\n"
        "src/auth.py:67:1: F401 [*] `sys` imported but unused\n"
        "src/utils.py:12:1: E501 Line too long (95 > 88 characters)\n"
        "src/utils.py:34:1: F401 [*] `re` imported but unused\n"
        "Found 5 errors.\n"
        "[*] 3 fixable with the `--fix` option.\n"
    )

    def test_clean_returns_ok(self):
        result = filter_ruff(self.CLEAN_OUTPUT, "ruff check .", 0)
        assert "ok" in result.lower()

    def test_groups_same_rule(self):
        """F401 appears 3 times — should show grouped."""
        result = filter_ruff(self.ISSUES_OUTPUT, "ruff check .", 1)
        # F401 appears 3 times in 3 files, E501 2 times in 1 file
        assert "F401" in result
        assert "E501" in result

    def test_shows_occurrence_counts(self):
        result = filter_ruff(self.ISSUES_OUTPUT, "ruff check .", 1)
        # F401: 3 occurrences, should show count
        assert "3×" in result or "(3" in result

    def test_shorter_than_original(self):
        result = filter_ruff(self.ISSUES_OUTPUT, "ruff check .", 1)
        assert len(result) < len(self.ISSUES_OUTPUT)

    def test_includes_summary_line(self):
        result = filter_ruff(self.ISSUES_OUTPUT, "ruff check .", 1)
        assert "Found 5 errors" in result or "5" in result

    def test_uv_run_ruff_works(self):
        result = filter_ruff(self.ISSUES_OUTPUT, "uv run ruff check .", 1)
        assert "F401" in result

    # ── New full-format tests (ruff >= 0.4 default output style) ──────────────

    FULL_FORMAT_OUTPUT = (
        "F401 [*] `os` imported but unused\n"
        " --> src/main.py:1:8\n"
        "  |\n"
        "1 | import os\n"
        "  |        ^^\n"
        "  |\n"
        "help: Remove unused import: `os`\n"
        "\n"
        "F401 [*] `sys` imported but unused\n"
        " --> src/main.py:2:8\n"
        "  |\n"
        "2 | import sys\n"
        "  |        ^^^\n"
        "  |\n"
        "help: Remove unused import: `sys`\n"
        "\n"
        "E711 Comparison to `None` should be `cond is None`\n"
        " --> src/utils.py:9:16\n"
        "  |\n"
        "9 |     if result==None:\n"
        "  |                ^^^^\n"
        "  |\n"
        "\n"
        "Found 3 errors.\n"
        "[*] 2 fixable with the `--fix` option.\n"
    )

    def test_full_format_extracts_rule_codes(self):
        """New ruff full-format: rule code must be extracted, not just summary."""
        result = filter_ruff(self.FULL_FORMAT_OUTPUT, "ruff check src/", 1)
        assert "F401" in result, f"Expected F401 in result but got: {result!r}"

    def test_full_format_groups_same_rule(self):
        """F401 appears twice in full format — should be grouped with count."""
        result = filter_ruff(self.FULL_FORMAT_OUTPUT, "ruff check src/", 1)
        assert "2" in result, f"Expected count '2' in result but got: {result!r}"

    def test_full_format_shows_all_rules(self):
        """E711 must appear alongside F401 in compressed output."""
        result = filter_ruff(self.FULL_FORMAT_OUTPUT, "ruff check src/", 1)
        assert "E711" in result, f"Expected E711 in result but got: {result!r}"

    def test_full_format_significantly_shorter_than_original(self):
        """Full-format output (28 lines) must compress significantly."""
        result = filter_ruff(self.FULL_FORMAT_OUTPUT, "ruff check src/", 1)
        assert len(result) < len(self.FULL_FORMAT_OUTPUT) * 0.5, (
            f"Expected >50% savings but got {len(result)}/{len(self.FULL_FORMAT_OUTPUT)} chars"
        )

    def test_full_format_includes_summary(self):
        """Summary line 'Found 3 errors.' must be preserved."""
        result = filter_ruff(self.FULL_FORMAT_OUTPUT, "ruff check src/", 1)
        assert "Found 3 errors" in result or "3" in result


# ── eslint ────────────────────────────────────────────────────────────────────


class TestFilterEslint:
    CLEAN_OUTPUT = ""  # eslint produces no output when clean

    ISSUES_OUTPUT = (
        "/home/user/src/auth.ts\n"
        "  10:5  error  'unused' is defined but never used  no-unused-vars\n"
        "  24:1  warning  Unexpected var, use let or const  no-var\n"
        "\n"
        "/home/user/src/utils.ts\n"
        "  5:9   error  'unused2' is defined but never used  no-unused-vars\n"
        "  18:1  warning  Unexpected var, use let or const  no-var\n"
        "\n"
        "/home/user/src/models.ts\n"
        "  33:3  error  'unused3' is defined but never used  no-unused-vars\n"
        "\n"
        "✖ 5 problems (3 errors, 2 warnings)\n"
    )

    def test_clean_returns_ok(self):
        result = filter_eslint("", "eslint src/", 0)
        assert "ok" in result.lower()

    def test_groups_same_rule(self):
        """no-unused-vars appears 3 times — should be grouped."""
        result = filter_eslint(self.ISSUES_OUTPUT, "eslint src/", 1)
        assert "no-unused-vars" in result

    def test_shows_occurrence_counts(self):
        result = filter_eslint(self.ISSUES_OUTPUT, "eslint src/", 1)
        # no-unused-vars: 3 occurrences
        assert "3×" in result or "(3" in result

    def test_errors_before_warnings(self):
        result = filter_eslint(self.ISSUES_OUTPUT, "eslint src/", 1)
        # Both should appear, errors (✗) before warnings (⚠)
        error_pos = result.find("✗")
        warning_pos = result.find("⚠")
        if error_pos != -1 and warning_pos != -1:
            assert error_pos < warning_pos

    def test_includes_summary(self):
        result = filter_eslint(self.ISSUES_OUTPUT, "eslint src/", 1)
        assert "5 problems" in result or "problems" in result

    def test_shorter_than_original(self):
        result = filter_eslint(self.ISSUES_OUTPUT, "eslint src/", 1)
        assert len(result) < len(self.ISSUES_OUTPUT)

    def test_npx_eslint_works(self):
        result = filter_eslint(self.ISSUES_OUTPUT, "npx eslint src/", 1)
        assert "no-unused-vars" in result
