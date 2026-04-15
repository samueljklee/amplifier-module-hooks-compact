"""YAML filter pipeline engine.

Executes a declarative 6-stage pipeline:
1. strip_lines_matching / keep_lines_matching (mutually exclusive)
2. replace  — regex substitutions (chainable list)
3. head_lines / tail_lines — keep first/last N lines
4. max_lines — absolute cap
5. on_empty  — fallback message when everything is filtered out
"""

from __future__ import annotations

import re
from typing import Any


def apply_yaml_filter(output: str, config: dict[str, Any]) -> str:
    """Apply a YAML-defined filter pipeline to command output.

    Stages run in strict order. Each stage is optional; omit the key to skip it.

    Args:
        output: Pre-processed command output string.
        config: YAML filter configuration dict.

    Returns:
        Filtered output string (may be empty if everything was stripped).
    """
    lines = output.split("\n")

    # ── Stage 1: Line filtering ───────────────────────────────────────────────
    # strip_lines_matching and keep_lines_matching are mutually exclusive.
    # strip takes precedence if both are present.
    strip_patterns: list[str] | None = config.get("strip_lines_matching")
    keep_patterns: list[str] | None = config.get("keep_lines_matching")

    if strip_patterns:
        compiled = [re.compile(p) for p in strip_patterns]
        lines = [line for line in lines if not any(p.search(line) for p in compiled)]
    elif keep_patterns:
        compiled = [re.compile(p) for p in keep_patterns]
        lines = [line for line in lines if any(p.search(line) for p in compiled)]

    # ── Stage 2: Regex replacements (chainable) ───────────────────────────────
    replacements: list[dict[str, str]] | None = config.get("replace")
    if replacements:
        text = "\n".join(lines)
        for r in replacements:
            pattern = r.get("pattern", "")
            replacement = r.get("replacement", "")
            if pattern:
                text = re.sub(pattern, replacement, text)
        lines = text.split("\n")

    # ── Stage 3: Head / tail lines ────────────────────────────────────────────
    head: int | None = config.get("head_lines")
    tail: int | None = config.get("tail_lines")

    if head is not None and tail is not None:
        # Both: keep head from start, tail from end (with separator if they overlap)
        total = len(lines)
        if head + tail < total:
            lines = lines[:head] + ["..."] + lines[-tail:]
        # else: head + tail >= total → keep all lines (they already overlap)
    elif head is not None:
        lines = lines[:head]
    elif tail is not None:
        lines = lines[-tail:] if tail <= len(lines) else lines

    # ── Stage 4: Max lines ────────────────────────────────────────────────────
    max_lines: int | None = config.get("max_lines")
    if max_lines is not None and len(lines) > max_lines:
        truncated_count = len(lines) - max_lines
        lines = lines[:max_lines]
        lines.append(f"... [{truncated_count} more lines]")

    result = "\n".join(lines)

    # ── Stage 5: On-empty fallback ────────────────────────────────────────────
    if not result.strip():
        on_empty: str = config.get("on_empty", "")
        return on_empty

    return result
