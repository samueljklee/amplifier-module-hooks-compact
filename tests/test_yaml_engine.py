"""Tests for the YAML filter pipeline engine (apply_yaml_filter).

Covers all 6 pipeline stages individually, stage ordering, strip/keep
mutual exclusion, and on_empty fallback behaviour.
"""

from __future__ import annotations

from amplifier_module_hooks_compact.filters.yaml_engine import apply_yaml_filter


# ── Stage 1a: strip_lines_matching ─────────────────────────────────────────


class TestStripLinesMatching:
    def test_removes_matching_lines(self) -> None:
        """Lines that match a strip pattern are removed."""
        config: dict = {"strip_lines_matching": [r"^NOISE:"]}
        output = "keep this\nNOISE: foo\nand this\nNOISE: bar"
        result = apply_yaml_filter(output, config)
        assert "keep this" in result
        assert "and this" in result
        assert "NOISE: foo" not in result
        assert "NOISE: bar" not in result

    def test_multiple_patterns_all_apply(self) -> None:
        """Every strip pattern is applied; any match removes the line."""
        config: dict = {"strip_lines_matching": [r"^AAA", r"^BBB"]}
        output = "AAA first\nBBB second\nCCC third"
        result = apply_yaml_filter(output, config)
        assert "CCC third" in result
        assert "AAA first" not in result
        assert "BBB second" not in result

    def test_strips_blank_lines(self) -> None:
        """Blank-line strip pattern removes empty lines."""
        config: dict = {"strip_lines_matching": [r"^\s*$"]}
        output = "line one\n\nline two\n\nline three"
        result = apply_yaml_filter(output, config)
        assert "\n\n" not in result
        assert "line one" in result
        assert "line three" in result

    def test_no_strip_patterns_keeps_all_lines(self) -> None:
        """When strip_lines_matching is absent, no lines are removed."""
        config: dict = {}
        output = "line 1\nline 2\nline 3"
        result = apply_yaml_filter(output, config)
        assert result == output


# ── Stage 1b: keep_lines_matching ──────────────────────────────────────────


class TestKeepLinesMatching:
    def test_retains_only_matching_lines(self) -> None:
        """Only lines matching at least one keep pattern are kept."""
        config: dict = {"keep_lines_matching": [r"^KEEP"]}
        output = "KEEP this\ndrop this\nKEEP that\ndrop that"
        result = apply_yaml_filter(output, config)
        assert "KEEP this" in result
        assert "KEEP that" in result
        assert "drop this" not in result
        assert "drop that" not in result

    def test_multiple_keep_patterns(self) -> None:
        """A line matching any keep pattern is retained."""
        config: dict = {"keep_lines_matching": [r"^AAA", r"^BBB"]}
        output = "AAA one\nBBB two\nCCC three"
        result = apply_yaml_filter(output, config)
        assert "AAA one" in result
        assert "BBB two" in result
        assert "CCC three" not in result


# ── Mutual exclusion ────────────────────────────────────────────────────────


class TestStripKeepMutuallyExclusive:
    def test_strip_takes_precedence_over_keep(self) -> None:
        """When both strip and keep are present, strip runs; keep is ignored.

        Proof: 'other line' is retained even though it doesn't match keep.
        """
        config: dict = {
            "strip_lines_matching": [r"^STRIP"],
            "keep_lines_matching": [r"^KEEP"],
        }
        output = "KEEP me\nSTRIP me\nother line"
        result = apply_yaml_filter(output, config)

        assert "STRIP me" not in result  # stripped
        assert "KEEP me" in result  # not stripped
        # 'other line' would be gone if keep_lines_matching had run
        assert "other line" in result


# ── Stage 2: replace ────────────────────────────────────────────────────────


class TestReplace:
    def test_substitutes_matching_pattern(self) -> None:
        """replace applies a regex substitution to the full output text."""
        config: dict = {
            "replace": [
                {
                    "pattern": r"^Warning: foo already installed",
                    "replacement": "already installed (skipped)",
                }
            ]
        }
        output = "Warning: foo already installed\nother line"
        result = apply_yaml_filter(output, config)
        assert "Warning: foo already installed" not in result
        assert "already installed (skipped)" in result
        assert "other line" in result

    def test_chainable_replacements(self) -> None:
        """Multiple replace entries are applied in sequence (chained)."""
        config: dict = {
            "replace": [
                {"pattern": r"foo", "replacement": "bar"},
                {"pattern": r"bar", "replacement": "baz"},
            ]
        }
        output = "foo"
        result = apply_yaml_filter(output, config)
        assert result.strip() == "baz"

    def test_no_replace_config_leaves_output_unchanged(self) -> None:
        """When replace is absent, output is not changed."""
        config: dict = {}
        output = "hello world"
        result = apply_yaml_filter(output, config)
        assert result == output


# ── Stage 3a: head_lines ────────────────────────────────────────────────────


class TestHeadLines:
    def test_keeps_first_n_lines(self) -> None:
        """head_lines retains only the first N lines."""
        lines = [f"line {i}" for i in range(10)]
        config: dict = {"head_lines": 3}
        result = apply_yaml_filter("\n".join(lines), config)
        assert result.split("\n") == ["line 0", "line 1", "line 2"]

    def test_head_larger_than_input_keeps_all(self) -> None:
        """head_lines larger than the line count keeps everything."""
        config: dict = {"head_lines": 100}
        output = "a\nb\nc"
        result = apply_yaml_filter(output, config)
        assert result == "a\nb\nc"


# ── Stage 3b: tail_lines ────────────────────────────────────────────────────


class TestTailLines:
    def test_keeps_last_n_lines(self) -> None:
        """tail_lines retains only the last N lines."""
        lines = [f"line {i}" for i in range(10)]
        config: dict = {"tail_lines": 3}
        result = apply_yaml_filter("\n".join(lines), config)
        assert result.split("\n") == ["line 7", "line 8", "line 9"]

    def test_tail_larger_than_input_keeps_all(self) -> None:
        """tail_lines larger than the line count keeps everything."""
        config: dict = {"tail_lines": 100}
        output = "a\nb\nc"
        result = apply_yaml_filter(output, config)
        assert result == "a\nb\nc"


# ── Stage 4: max_lines ──────────────────────────────────────────────────────


class TestMaxLines:
    def test_truncates_and_appends_count_message(self) -> None:
        """max_lines truncates output and appends a '... [N more lines]' marker."""
        lines = [f"line {i}" for i in range(10)]
        config: dict = {"max_lines": 5}
        result = apply_yaml_filter("\n".join(lines), config)
        result_lines = result.split("\n")
        assert len(result_lines) == 6  # 5 content lines + 1 ellipsis marker
        assert "5 more lines" in result_lines[-1]

    def test_no_truncation_when_under_limit(self) -> None:
        """max_lines does not truncate when line count is within the limit."""
        config: dict = {"max_lines": 100}
        output = "a\nb\nc"
        result = apply_yaml_filter(output, config)
        assert result == "a\nb\nc"


# ── Stage 5: on_empty ───────────────────────────────────────────────────────


class TestOnEmpty:
    def test_fallback_returned_when_all_lines_stripped(self) -> None:
        """on_empty is returned when the filtered output is blank."""
        config: dict = {
            "strip_lines_matching": [r".*"],
            "on_empty": "make: ok",
        }
        result = apply_yaml_filter("strip everything", config)
        assert result == "make: ok"

    def test_fallback_not_triggered_when_content_remains(self) -> None:
        """on_empty is NOT triggered when filtered output is non-empty."""
        config: dict = {
            "strip_lines_matching": [r"^noise"],
            "on_empty": "fallback",
        }
        output = "keep this\nnoise: drop"
        result = apply_yaml_filter(output, config)
        assert result != "fallback"
        assert "keep this" in result

    def test_on_empty_defaults_to_empty_string(self) -> None:
        """When on_empty key is absent, an empty result stays empty."""
        config: dict = {"strip_lines_matching": [r".*"]}
        result = apply_yaml_filter("strip everything", config)
        assert result == ""


# ── Stage ordering ──────────────────────────────────────────────────────────


class TestStageOrdering:
    def test_strip_runs_before_max_lines(self) -> None:
        """Strip reduces line count before max_lines is applied.

        5 'keep' lines + 5 'strip' lines. max_lines=6 (> 5 remaining).
        After strip: 5 keep lines → max_lines=6 doesn't truncate.
        If max_lines ran first: 10 lines → truncated, marker would appear.
        """
        lines = [f"keep {i}" for i in range(5)] + [f"strip {i}" for i in range(5)]
        config: dict = {
            "strip_lines_matching": [r"^strip"],
            "max_lines": 6,
        }
        result = apply_yaml_filter("\n".join(lines), config)
        assert "... [" not in result  # no truncation marker

    def test_strip_runs_before_on_empty(self) -> None:
        """Strip stage runs; if result becomes empty, on_empty kicks in."""
        config: dict = {
            "strip_lines_matching": [r".*"],
            "on_empty": "all gone",
        }
        output = "\n".join([f"line {i}" for i in range(10)])
        result = apply_yaml_filter(output, config)
        assert result == "all gone"
