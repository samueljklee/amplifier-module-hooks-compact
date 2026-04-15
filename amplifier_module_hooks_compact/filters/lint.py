"""Lint tool output filters.

Strategy: group-by-rule compression.
Deduplicate repeated warnings and count occurrences per rule.
Reduces 80+ repeated lint warnings to a compact summary.
"""

from __future__ import annotations

import re
from collections import defaultdict


# ── Cargo clippy ──────────────────────────────────────────────────────────────

# warning: unused import: `std::collections::HashMap`
#   --> src/main.rs:1:5
# warning: variable does not need to be mutable
# ...
# warning: `myproject` (bin "myproject") generated 5 warnings
_CLIPPY_WARNING_RE = re.compile(r"^warning(\[(\w+)\])?: (.+)")
_CLIPPY_SUMMARY_RE = re.compile(r"^warning: `\S+`.*generated (\d+) warnings?")
_CLIPPY_ERROR_RE = re.compile(r"^error(\[E\d+\])?: (.+)")
_CLIPPY_ARROW_RE = re.compile(r"^\s+-->\s")


def filter_cargo_clippy(output: str, command: str, exit_code: int | None) -> str:
    """Compress cargo clippy output.

    Groups warnings by rule (lint code), deduplicates, and counts occurrences.
    Errors are always shown in full.
    """
    lines = output.split("\n")

    # Collect warnings grouped by rule
    # rule_code → (description, count, first_location)
    warnings: dict[str, dict] = defaultdict(
        lambda: {"description": "", "count": 0, "locations": []}
    )
    errors: list[str] = []
    summary_line = ""

    i = 0
    while i < len(lines):
        line = lines[i]

        # Summary line: "warning: `proj` generated N warnings"
        m_summary = _CLIPPY_SUMMARY_RE.match(line)
        if m_summary:
            summary_line = line.strip()
            i += 1
            continue

        # Error lines (always include full block)
        m_error = _CLIPPY_ERROR_RE.match(line)
        if m_error:
            block = [line]
            i += 1
            while i < len(lines) and (
                lines[i].startswith("  ")
                or lines[i].startswith("\t")
                or _CLIPPY_ARROW_RE.match(lines[i])
            ):
                block.append(lines[i])
                i += 1
            errors.append("\n".join(block))
            continue

        # Warning lines
        m_warning = _CLIPPY_WARNING_RE.match(line)
        if m_warning:
            rule_code = m_warning.group(2) or "misc"
            description = m_warning.group(3).strip()

            # Collect location line if present
            location = ""
            i += 1
            if i < len(lines) and _CLIPPY_ARROW_RE.match(lines[i]):
                location = lines[i].strip()
                i += 1
                # Skip the source context lines
                while i < len(lines) and (
                    lines[i].startswith("  ") or lines[i].startswith("\t")
                ):
                    i += 1

            w = warnings[rule_code]
            if w["count"] == 0:
                w["description"] = description
            w["count"] += 1
            if location and len(w["locations"]) < 3:
                w["locations"].append(location)
            continue

        i += 1

    # Format output
    result_parts: list[str] = []

    # Errors first
    result_parts.extend(errors)

    # Grouped warnings
    for rule_code, data in sorted(warnings.items(), key=lambda x: -x[1]["count"]):
        n = data["count"]
        desc = data["description"]
        if n == 1 and data["locations"]:
            result_parts.append(
                f"warning[{rule_code}]: {desc} ({data['locations'][0]})"
            )
        else:
            result_parts.append(f"warning[{rule_code}]: {desc} ({n}×)")
            for loc in data["locations"][:2]:
                result_parts.append(f"  {loc}")

    if summary_line:
        result_parts.append(summary_line)

    if not result_parts:
        if exit_code == 0:
            return "ok (no clippy warnings)"
        return output

    return "\n".join(result_parts)


# ── ruff check ────────────────────────────────────────────────────────────────

# src/main.py:10:1: F401 [*] `os` imported but unused
# src/auth.py:45:9: E501 Line too long (120 > 88)
_RUFF_LINE_RE = re.compile(r"^(.+):(\d+):(\d+): ([A-Z]\d+)\s+(.+)")
_RUFF_SUMMARY_RE = re.compile(r"^Found (\d+) error")


def filter_ruff(output: str, command: str, exit_code: int | None) -> str:
    """Compress ruff check output.

    Groups by rule code, deduplicates, and counts occurrences.
    """
    lines = output.split("\n")

    if exit_code == 0:
        return "ok (no ruff issues)"

    # rule_code → {"description": str, "count": int, "files": set}
    rule_groups: dict[str, dict] = defaultdict(
        lambda: {"description": "", "count": 0, "files": set()}
    )
    summary_line = ""

    for line in lines:
        m_sum = _RUFF_SUMMARY_RE.match(line)
        if m_sum:
            summary_line = line.strip()
            continue

        m = _RUFF_LINE_RE.match(line)
        if m:
            file_path, _lineno, _col, rule_code, description = m.groups()
            # Strip [*] fixable marker from description
            description = description.replace(" [*]", "").strip()
            g = rule_groups[rule_code]
            if g["count"] == 0:
                g["description"] = description
            g["count"] += 1
            g["files"].add(file_path)

    result_parts: list[str] = []
    for rule_code, data in sorted(rule_groups.items(), key=lambda x: -x[1]["count"]):
        n = data["count"]
        files = len(data["files"])
        desc = data["description"]
        if n == 1:
            result_parts.append(f"{rule_code}: {desc}")
        else:
            result_parts.append(f"{rule_code}: {desc} ({n}× in {files} file(s))")

    if summary_line:
        result_parts.append(summary_line)

    return "\n".join(result_parts) if result_parts else output


# ── ESLint ────────────────────────────────────────────────────────────────────

# /path/to/file.ts
#   10:5  error  'foo' is defined but never used  no-unused-vars
#   20:1  warning  Unexpected var, use let or const instead  no-var
#
# ✖ 15 problems (8 errors, 7 warnings)
_ESLINT_ISSUE_RE = re.compile(r"^\s+(\d+):(\d+)\s+(error|warning)\s+(.+?)\s{2,}(\S.*)$")
_ESLINT_SUMMARY_RE = re.compile(r"^[✖✓]\s+\d+ problem")


def filter_eslint(output: str, command: str, exit_code: int | None) -> str:
    """Compress ESLint output.

    Groups by rule name, deduplicates, and counts occurrences.
    """
    if exit_code == 0:
        return "ok (no eslint issues)"

    lines = output.split("\n")

    # rule_name → {"severity": str, "message": str, "count": int}
    rule_groups: dict[str, dict] = defaultdict(
        lambda: {"severity": "", "message": "", "count": 0}
    )
    summary_line = ""

    for line in lines:
        m_sum = _ESLINT_SUMMARY_RE.match(line)
        if m_sum:
            summary_line = line.strip()
            continue

        m = _ESLINT_ISSUE_RE.match(line)
        if m:
            _lineno, _col, severity, message, rule_name = m.groups()
            g = rule_groups[rule_name]
            if g["count"] == 0:
                g["severity"] = severity
                g["message"] = message.strip()
            g["count"] += 1

    result_parts: list[str] = []
    # Errors first, then warnings
    for severity in ("error", "warning"):
        for rule_name, data in sorted(
            rule_groups.items(), key=lambda x: -x[1]["count"]
        ):
            if data["severity"] != severity:
                continue
            n = data["count"]
            msg = data["message"]
            prefix = "✗" if severity == "error" else "⚠"
            if n == 1:
                result_parts.append(f"{prefix} {rule_name}: {msg}")
            else:
                result_parts.append(f"{prefix} {rule_name}: {msg} ({n}×)")

    if summary_line:
        result_parts.append(summary_line)

    return "\n".join(result_parts) if result_parts else output
