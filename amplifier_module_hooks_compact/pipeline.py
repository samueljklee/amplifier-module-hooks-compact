"""Universal pre-processing applied to all matched bash output.

Three stages run in order:
1. Strip ANSI escape codes (color, bold, etc.)
2. Collapse consecutive blank lines to single blank
3. Truncate lines exceeding max_line_length
"""

from __future__ import annotations

import re

# Matches ANSI/VT100 escape sequences:
#   CSI sequences: ESC [ ... [A-Za-z]
#   OSC sequences: ESC ] ... BEL
#   SS3/other single-char sequences
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]"  # CSI sequences (colors, cursor, etc.)
    r"|\x1b\][^\x07]*\x07"  # OSC sequences (window title, etc.)
    r"|\x1b[PX^_][^\x1b]*\x1b\\"  # DCS / PM / APC / SOS / ST
    r"|\x1b[@-Z\\-_]"  # 2-char Fe sequences
    r"|\x9b[0-9;?]*[A-Za-z]"  # C1 CSI (8-bit variant)
)

# Matches 3+ consecutive newlines (to collapse to 2)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text.

    Args:
        text: Raw string that may contain ANSI codes.

    Returns:
        String with all ANSI codes removed.
    """
    return _ANSI_RE.sub("", text)


def collapse_blank_lines(text: str) -> str:
    """Collapse 3+ consecutive newlines down to 2 (single blank line).

    Args:
        text: Input string.

    Returns:
        String with at most one consecutive blank line.
    """
    return _MULTI_BLANK_RE.sub("\n\n", text)


def truncate_long_lines(text: str, max_chars: int = 500) -> str:
    """Truncate lines exceeding max_chars characters.

    Args:
        text: Input string.
        max_chars: Maximum characters per line (0 = unlimited).

    Returns:
        String with long lines truncated and marked.
    """
    if max_chars <= 0:
        return text
    lines = text.split("\n")
    truncated = []
    for line in lines:
        if len(line) > max_chars:
            truncated.append(line[:max_chars] + "... [truncated]")
        else:
            truncated.append(line)
    return "\n".join(truncated)


def preprocess(
    text: str,
    *,
    strip_ansi: bool = True,
    max_line_length: int = 500,
) -> str:
    """Apply universal pre-processing to raw command output.

    Runs three stages in order:
    1. Strip ANSI escape codes (if strip_ansi=True)
    2. Collapse consecutive blank lines
    3. Truncate long lines

    Args:
        text: Raw command output string.
        strip_ansi: Whether to remove ANSI escape codes.
        max_line_length: Maximum characters per line (0 = unlimited).

    Returns:
        Pre-processed text ready for command-specific filtering.
    """
    if not text:
        return text

    # Stage 1: Strip ANSI escape codes
    if strip_ansi:
        text = _ANSI_RE.sub("", text)

    # Stage 2: Collapse consecutive blank lines
    text = _MULTI_BLANK_RE.sub("\n\n", text)

    # Stage 3: Truncate long lines
    if max_line_length > 0:
        lines = text.split("\n")
        truncated = []
        for line in lines:
            if len(line) > max_line_length:
                truncated.append(line[:max_line_length] + "... [truncated]")
            else:
                truncated.append(line)
        text = "\n".join(truncated)

    return text
