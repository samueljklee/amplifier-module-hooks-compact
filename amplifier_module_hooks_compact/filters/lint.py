"""Lint tool output filters.

Strategy: group-by-rule compression.
Deduplicate repeated warnings and count occurrences per rule.
Each occurrence preserves file:line so the model can navigate to and fix
every violation WITHOUT re-running the linter.
"""

from __future__ import annotations

import re
from collections import defaultdict


# ── Cargo clippy ────────────────────────────────────────────────────────────

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
    Each occurrence preserves file:line so the model can fix every warning
    without re-running clippy.
    Errors are always shown in full.
    """
    lines = output.split("\n")

    # rule_group_key → {rule_code, items: [(description, location_str)], count}
    warnings: dict[str, dict] = defaultdict(
        lambda: {"rule_code": "", "items": [], "count": 0}
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
                # Skip source context lines
                while i < len(lines) and (
                    lines[i].startswith("  ") or lines[i].startswith("\t")
                ):
                    i += 1

            # For "misc" warnings (no lint code), use description as the grouping
            # key so that "function `add` is never used" and "function `foo` is
            # never used" are NOT merged — the model needs to see each unique name.
            group_key = rule_code if rule_code != "misc" else f"misc:{description}"

            w = warnings[group_key]
            if w["count"] == 0:
                w["rule_code"] = rule_code
            w["count"] += 1
            w["items"].append((description, location))
            continue

        i += 1

    # Format output
    result_parts: list[str] = []

    # Errors first
    result_parts.extend(errors)

    # Grouped warnings — sorted by count descending
    for _key, data in sorted(warnings.items(), key=lambda x: -x[1]["count"]):
        n = data["count"]
        items = data["items"]  # list of (description, location_str)
        display_code = data.get("rule_code", "misc")

        # Check how many unique descriptions we have
        unique_descs = list(dict.fromkeys(desc for desc, _ in items))

        if n == 1:
            desc, loc = items[0]
            loc_str = f" ({loc})" if loc else ""
            result_parts.append(f"warning[{display_code}]: {desc}{loc_str}")
        elif len(unique_descs) == 1:
            # All same description (e.g. same rule, same message) — show count + ALL locations
            result_parts.append(f"warning[{display_code}]: {unique_descs[0]} ({n}×)")
            shown = items[:50]  # safety valve at 50, not 5
            for desc, loc in shown:
                if loc:
                    result_parts.append(f"  {loc}")
            if n > 50:
                result_parts.append(f"  (+{n - 50} more — run cargo clippy for full list)")
        else:
            # Different descriptions per occurrence (e.g. unused variable `x` vs `y`)
            # Show EVERY occurrence with its location so model knows every name and where to fix it.
            # Crusty's rule: never hide actionable items behind a count.
            result_parts.append(f"warning[{display_code}] ({n}×):")
            shown = items[:50]  # safety valve at 50, not 5
            for desc, loc in shown:
                loc_str = f" ({loc})" if loc else ""
                result_parts.append(f"  {desc}{loc_str}")
            if n > 50:
                result_parts.append(f"  (+{n - 50} more — run cargo clippy for full list)")

    if summary_line:
        result_parts.append(summary_line)

    if not result_parts:
        if exit_code == 0:
            return "ok (no clippy warnings)"
        return output

    return "\n".join(result_parts)


# ── ruff check ───────────────────────────────────────────────────────────────

# ── Concise format (old/explicit): file:line:col: CODE [*] description ──────
# src/main.py:10:1: F401 [*] `os` imported but unused
_RUFF_LINE_RE = re.compile(r"^(.+):(\d+):(\d+): ([A-Z]\d+)\s+(.+)")
# ── Full format (ruff default since ~0.4): code on its own line, loc below ──
# F401 [*] `os` imported but unused
#  --> src/main.py:1:8
_RUFF_FULL_CODE_RE = re.compile(r"^([A-Z]\d+)(?:\s*\[.*?\])?\s+(.+)")
_RUFF_FULL_LOC_RE = re.compile(r"^\s+-->\s+(.+?):(\d+):(\d+)")
_RUFF_SUMMARY_RE = re.compile(r"^Found \d+ error")


def filter_ruff(output: str, command: str, exit_code: int | None) -> str:
    """Compress ruff check output.

    Groups by rule code, deduplicates, and counts occurrences.
    Handles both the old concise format (file:line:col: CODE desc)
    and the new full/rich format (CODE desc \\n --> file:line:col).

    CRITICAL for continuation: each occurrence shows its file:line so the model
    can fix every violation without re-running ruff.
    """
    if exit_code == 0:
        return "ok (no ruff issues)"

    lines = output.split("\n")

    # rule_code → {items: [(description, location_str)], count}
    # location_str: "file.py:10" or "" if not available
    rule_groups: dict[str, dict] = defaultdict(lambda: {"items": [], "count": 0})
    summary_line = ""

    i = 0
    while i < len(lines):
        line = lines[i]

        # Summary line: "Found N errors."
        if _RUFF_SUMMARY_RE.match(line):
            summary_line = line.strip()
            i += 1
            continue

        # Concise format: file:line:col: CODE [*] description
        m_concise = _RUFF_LINE_RE.match(line)
        if m_concise:
            file_path, lineno, _col, rule_code, description = m_concise.groups()
            description = re.sub(r"\s*\[.*?\]", "", description).strip()
            g = rule_groups[rule_code]
            g["items"].append((description, f"{file_path}:{lineno}"))
            g["count"] += 1
            i += 1
            continue

        # Full format: CODE [*] description (on its own line)
        m_full = _RUFF_FULL_CODE_RE.match(line)
        if m_full:
            rule_code = m_full.group(1)
            description = m_full.group(2).strip()
            # Strip fix indicator like [*] from description if present
            description = re.sub(r"^\s*\[.*?\]\s*", "", description).strip()
            location = ""
            i += 1
            # Peek at the next non-empty line for " --> file:line:col"
            if i < len(lines):
                m_loc = _RUFF_FULL_LOC_RE.match(lines[i])
                if m_loc:
                    location = f"{m_loc.group(1)}:{m_loc.group(2)}"
                    i += 1
            g = rule_groups[rule_code]
            g["items"].append((description, location))
            g["count"] += 1
            continue

        i += 1

    result_parts: list[str] = []
    for rule_code, data in sorted(rule_groups.items(), key=lambda x: -x[1]["count"]):
        n = data["count"]
        items = data["items"]  # list of (description, location_str)

        # Deduplicate descriptions while preserving order; pair each with its location
        seen_descs: set[str] = set()
        unique_items: list[tuple[str, str]] = []
        for desc, loc in items:
            if desc not in seen_descs:
                seen_descs.add(desc)
                unique_items.append((desc, loc))

        if n == 1:
            desc, loc = unique_items[0]
            loc_str = f" ({loc})" if loc else ""
            result_parts.append(f"{rule_code}: {desc}{loc_str}")
        elif len(unique_items) == 1:
            # Multiple occurrences, all identical descriptions — show count + ALL locations.
            # Crusty's rule: never hide actionable items behind a count.
            desc = unique_items[0][0]
            locs = [loc for _, loc in items if loc]
            shown_locs = locs[:50]  # safety valve at 50, not 5
            if shown_locs:
                locs_str = ", ".join(shown_locs)
                result_parts.append(f"{rule_code} ({n}×): {desc} → {locs_str}")
                if len(locs) > 50:
                    result_parts.append(f"  (+{len(locs) - 50} more — run ruff for full list)")
            else:
                result_parts.append(f"{rule_code} ({n}×): {desc}")
        else:
            # Multiple unique descriptions — show ALL with their locations.
            # Crusty's rule: never hide actionable items behind a count.
            # Safety valve at 50 (not 5) prevents truly pathological output.
            lines_out = [f"{rule_code} ({n}×):"]
            shown = unique_items[:50]
            for desc, loc in shown:
                loc_str = f" → {loc}" if loc else ""
                lines_out.append(f"  {desc}{loc_str}")
            if len(unique_items) > 50:
                rest = len(unique_items) - 50
                lines_out.append(f"  (+{rest} more — run ruff for full list)")
            result_parts.append("\n".join(lines_out))

    if summary_line:
        result_parts.append(summary_line)

    return "\n".join(result_parts) if result_parts else output


# ── ESLint ───────────────────────────────────────────────────────────────────

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
    Each occurrence preserves file:line so the model can fix every violation
    without re-running ESLint.
    """
    if exit_code == 0:
        # Don't expand already-compact clean output
        if len(output.strip()) < 30:
            return output.strip() if output.strip() else "ok (no eslint issues)"
        return "ok (no eslint issues)"

    lines = output.split("\n")

    # rule_name → {severity, items: [(message, file_loc)], count}
    # file_loc: "path/file.ts:10" or "" if not available
    rule_groups: dict[str, dict] = defaultdict(
        lambda: {"severity": "", "items": [], "count": 0}
    )
    summary_line = ""
    current_file = ""

    for line in lines:
        # Summary line: "✖ N problems"
        if _ESLINT_SUMMARY_RE.match(line):
            summary_line = line.strip()
            continue

        # Issue line (has leading whitespace): "  10:5  error  msg  rule-name"
        m = _ESLINT_ISSUE_RE.match(line)
        if m:
            lineno, _col, severity, message, rule_name = m.groups()
            g = rule_groups[rule_name]
            if g["count"] == 0:
                g["severity"] = severity
            file_loc = f"{current_file}:{lineno}" if current_file else f"line {lineno}"
            g["items"].append((message.strip(), file_loc))
            g["count"] += 1
            continue

        # File header: non-empty line with no leading whitespace (not summary)
        stripped = line.strip()
        if stripped and not line[0].isspace():
            current_file = stripped

    result_parts: list[str] = []
    # Errors first, then warnings
    for severity in ("error", "warning"):
        for rule_name, data in sorted(
            rule_groups.items(), key=lambda x: -x[1]["count"]
        ):
            if data["severity"] != severity:
                continue
            n = data["count"]
            items = data["items"]  # list of (message, file_loc)
            prefix = "✗" if severity == "error" else "⚠"

            # Check how many unique messages we have
            unique_msgs = list(dict.fromkeys(msg for msg, _ in items))

            if n == 1:
                msg, file_loc = items[0]
                loc_str = f" ({file_loc})" if file_loc else ""
                result_parts.append(f"{prefix} {rule_name}: {msg}{loc_str}")
            elif len(unique_msgs) == 1:
                # Same message, different files — show ALL locations.
                # Crusty's rule: never hide actionable items behind a count.
                msg = unique_msgs[0]
                locs = [loc for _, loc in items if loc]
                shown_locs = locs[:50]  # safety valve at 50, not 5
                if shown_locs:
                    locs_str = ", ".join(shown_locs)
                    result_parts.append(
                        f"{prefix} {rule_name} ({n}×): {msg} → {locs_str}"
                    )
                    if len(locs) > 50:
                        result_parts.append(f"  (+{len(locs) - 50} more — run eslint for full list)")
                else:
                    result_parts.append(f"{prefix} {rule_name}: {msg} ({n}×)")
            else:
                # Different messages per occurrence — show EVERY occurrence with file:line.
                # Crusty's rule: never hide actionable items behind a count.
                # Safety valve at 50 (not 5) prevents truly pathological output.
                result_parts.append(f"{prefix} {rule_name} ({n}×):")
                shown = items[:50]
                for msg, file_loc in shown:
                    loc_str = f" → {file_loc}" if file_loc else ""
                    result_parts.append(f"  {msg}{loc_str}")
                if n > 50:
                    result_parts.append(f"  (+{n - 50} more — run eslint for full list)")

    if summary_line:
        result_parts.append(summary_line)

    return "\n".join(result_parts) if result_parts else output
