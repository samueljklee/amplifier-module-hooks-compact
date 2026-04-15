"""Unit tests for the universal pre-processing pipeline."""

from __future__ import annotations


from amplifier_module_hooks_compact.pipeline import (
    collapse_blank_lines,
    preprocess,
    strip_ansi,
    truncate_long_lines,
)


class TestStripAnsi:
    def test_strips_color_codes(self):
        raw = "\033[31merror\033[0m: something failed"
        result = preprocess(raw)
        assert "\033[" not in result
        assert "error: something failed" in result

    def test_strips_bold(self):
        raw = "\033[1mbold text\033[0m"
        result = preprocess(raw)
        assert "bold text" in result
        assert "\033[" not in result

    def test_strips_256_color(self):
        raw = "\033[38;5;196mred text\033[0m"
        result = preprocess(raw)
        assert "red text" in result
        assert "\033[" not in result

    def test_strips_cursor_movement(self):
        raw = "\033[2J\033[H output"
        result = preprocess(raw)
        assert "\033[" not in result

    def test_passthrough_clean_text(self):
        raw = "no ansi here"
        assert preprocess(raw) == "no ansi here"

    def test_empty_string_unchanged(self):
        assert preprocess("") == ""

    def test_strip_ansi_disabled(self):
        raw = "\033[31mred\033[0m"
        result = preprocess(raw, strip_ansi=False)
        assert "\033[31m" in result

    def test_standalone_strip_ansi_function(self):
        raw = "\033[31merror\033[0m"
        assert "\033[" not in strip_ansi(raw)
        assert "error" in strip_ansi(raw)


class TestCollapseBlankLines:
    def test_collapses_three_consecutive_blanks(self):
        raw = "line1\n\n\n\nline2"
        result = preprocess(raw)
        assert result == "line1\n\nline2"

    def test_collapses_many_consecutive_blanks(self):
        raw = "a\n\n\n\n\n\n\nb"
        result = preprocess(raw)
        assert result == "a\n\nb"

    def test_preserves_single_blank(self):
        raw = "line1\n\nline2"
        result = preprocess(raw)
        assert result == "line1\n\nline2"

    def test_preserves_no_blank(self):
        raw = "line1\nline2\nline3"
        result = preprocess(raw)
        assert result == "line1\nline2\nline3"

    def test_standalone_collapse_blank_lines(self):
        raw = "a\n\n\n\nb"
        assert collapse_blank_lines(raw) == "a\n\nb"


class TestTruncateLongLines:
    def test_truncates_lines_over_500_chars(self):
        long_line = "x" * 600
        result = preprocess(long_line, max_line_length=500)
        lines = result.split("\n")
        # 500 chars + "... [truncated]" marker
        assert len(lines[0]) <= 520

    def test_truncation_marker_added(self):
        long_line = "y" * 600
        result = preprocess(long_line, max_line_length=500)
        assert "[truncated]" in result

    def test_preserves_short_lines(self):
        short = "short line"
        result = preprocess(short)
        assert result == "short line"

    def test_custom_max_line_length(self):
        line = "a" * 100
        result = preprocess(line, max_line_length=50)
        # First 50 chars + truncation marker
        assert result.startswith("a" * 50)
        assert "[truncated]" in result

    def test_unlimited_lines_when_zero(self):
        long_line = "z" * 1000
        result = preprocess(long_line, max_line_length=0)
        assert result == long_line

    def test_standalone_truncate_function(self):
        line = "b" * 200
        result = truncate_long_lines(line, max_chars=100)
        assert "[truncated]" in result
        assert len(result) <= 120


class TestPreprocessCombined:
    def test_all_three_stages_in_order(self):
        """ANSI stripped, blank lines collapsed, long lines truncated."""
        raw = "\033[31m" + "x" * 600 + "\033[0m\n\n\n\nclean line"
        result = preprocess(raw, max_line_length=500)
        assert "\033[" not in result
        assert "\n\n\n" not in result  # blanks collapsed
        assert "[truncated]" in result  # long line truncated

    def test_multiline_ansi(self):
        raw = "\033[32mline1\033[0m\n\033[33mline2\033[0m"
        result = preprocess(raw)
        assert "line1" in result
        assert "line2" in result
        assert "\033[" not in result
