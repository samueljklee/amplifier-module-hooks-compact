"""Build tool output filters.

Strategy: error-only compression.
- Strip success/progress noise
- Keep errors and warnings
- Success short-circuit when exit code 0
"""

from __future__ import annotations

import re

# Lines that indicate compilation progress (safe to strip on success)
_CARGO_PROGRESS_RE = re.compile(
    r"^\s*(Compiling|Downloading|Downloaded|Fetching|Checking|Blocking|Updating|"
    r"Locking|Resolving|Unpacking|Fresh|Dirty)\s"
)
_CARGO_FINISH_RE = re.compile(r"^\s*Finished\s")
_CARGO_ERROR_RE = re.compile(r"^error(\[E\d+\])?[: ]")
_CARGO_WARNING_RE = re.compile(r"^warning(\[.*?\])?[: ]")
_CARGO_ARROW_RE = re.compile(r"^\s+-->\s")


def filter_cargo_build(output: str, command: str, exit_code: int | None) -> str:
    """Compress cargo build output.

    Success (exit_code=0): return "ok (build succeeded)" plus any warnings.
    Failure: keep errors, warnings, and source location arrows.
    """
    lines = output.split("\n")

    if exit_code == 0:
        # Keep only warnings (errors shouldn't appear, but just in case)
        warnings = []
        i = 0
        while i < len(lines):
            if _CARGO_WARNING_RE.match(lines[i]):
                # Collect the full warning block (warning + location + maybe context)
                block = [lines[i]]
                i += 1
                while i < len(lines) and (
                    lines[i].startswith("  ")
                    or lines[i].startswith("\t")
                    or _CARGO_ARROW_RE.match(lines[i])
                ):
                    block.append(lines[i])
                    i += 1
                warnings.extend(block)
            else:
                i += 1

        if warnings:
            return "ok (build succeeded, with warnings)\n" + "\n".join(warnings)
        return "ok (build succeeded)"

    # Failure: keep errors, warnings, and source arrows
    error_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _CARGO_ERROR_RE.match(line) or _CARGO_WARNING_RE.match(line):
            error_lines.append(line)
            i += 1
            # Include source location and context lines
            while i < len(lines) and (
                lines[i].startswith("  ")
                or lines[i].startswith("\t")
                or _CARGO_ARROW_RE.match(lines[i])
            ):
                error_lines.append(lines[i])
                i += 1
        elif _CARGO_FINISH_RE.match(line):
            error_lines.append(line.strip())
            i += 1
        else:
            i += 1

    return "\n".join(error_lines) if error_lines else output


# ── TypeScript compiler (tsc) ─────────────────────────────────────────────────

# TypeScript error: src/auth.ts(45,9): error TS2339: Property 'foo' does not exist...
_TSC_ERROR_RE = re.compile(r"^.+\(\d+,\d+\): error TS\d+:")
_TSC_WARNING_RE = re.compile(r"^.+\(\d+,\d+\): warning TS\d+:")


def filter_tsc(output: str, command: str, exit_code: int | None) -> str:
    """Compress TypeScript compiler output.

    Error-only strategy: keep type errors, strip compilation success noise.
    """
    lines = output.split("\n")
    errors = [
        line
        for line in lines
        if _TSC_ERROR_RE.match(line) or _TSC_WARNING_RE.match(line)
    ]

    if not errors:
        if exit_code == 0:
            return "ok (no TypeScript errors)"
        # Non-zero but no recognizable errors — return last few lines
        non_empty = [ln for ln in lines if ln.strip()]
        return "\n".join(non_empty[-10:]) if non_empty else output

    error_count = sum(1 for ln in errors if " error TS" in ln)
    warning_count = sum(1 for ln in errors if " warning TS" in ln)
    summary_parts = []
    if error_count:
        summary_parts.append(f"{error_count} error(s)")
    if warning_count:
        summary_parts.append(f"{warning_count} warning(s)")

    return "\n".join(errors) + f"\n✗ {', '.join(summary_parts)}"


# ── npm build ──────────────────────────────────────────────────────────────────

_NPM_ERROR_RE = re.compile(r"(ERROR\s+in\s|npm ERR!|Error:)", re.IGNORECASE)


def filter_npm_build(output: str, command: str, exit_code: int | None) -> str:
    """Compress npm build output.

    Success short-circuit on exit_code=0.
    Failure: keep error lines.
    """
    if exit_code == 0:
        return "ok (build succeeded)"

    lines = output.split("\n")
    errors = [line for line in lines if _NPM_ERROR_RE.search(line)]

    if not errors:
        non_empty = [ln for ln in lines if ln.strip()]
        return "\n".join(non_empty[-15:]) if non_empty else output

    return "\n".join(errors)
