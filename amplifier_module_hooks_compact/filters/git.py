"""Git command output filters.

Compresses verbose git output using command-specific parsing strategies:
- git status:  strip hints/boilerplate, group by state, show counts (truncated for large repos)
- git diff:    diffstat summary + first N changed lines per file (not just file count)
- git log:     one-line-per-commit, strip author/date/stats
- git simple:  success short-circuit (push/pull/add/commit → "ok")
"""

from __future__ import annotations

import re

# Maximum items to show in staged/unstaged/untracked file lists.
# Large repos with many untracked files would otherwise produce minimal savings.
_MAX_LIST_ITEMS = 10

# git diff limits — keep enough context for the model to understand changes
# without drowning it in raw diff content.
_MAX_HUNK_LINES_PER_FILE = 8  # + and - lines shown per file
_MAX_FILES_WITH_HUNKS = 5  # max files to show hunk details for
_MAX_TOTAL_DIFF_LINES = 45  # absolute output line cap for git diff


def filter_git_status(output: str, command: str, exit_code: int | None) -> str:
    """Compress git status output.

    Strategy: strip instructional hints, group by staged/unstaged/untracked,
    show file counts and branch name. Truncates long file lists.

    Examples:
        >>> long_status = "On branch main\\n...42 hint lines...\\n"
        >>> result = filter_git_status(long_status, "git status", 0)
        >>> result.startswith("branch:")
        True
    """
    lines = output.split("\n")

    branch = "unknown"
    ahead_behind = ""
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    section: str | None = None

    for line in lines:
        stripped = line.strip()

        # Extract branch name
        if line.startswith("On branch "):
            branch = line[len("On branch ") :].strip()
            continue
        if line.startswith("HEAD detached at "):
            branch = f"(detached:{line[len('HEAD detached at ') :].strip()})"
            continue

        # Ahead/behind info
        if "Your branch is ahead" in line or "Your branch is behind" in line:
            # Extract the short summary
            m = re.search(r"(ahead .+ by \d+ commits?|behind .+ by \d+ commits?)", line)
            if m:
                ahead_behind = m.group(1)
            continue

        # Section headers — detect by key phrases
        if "Changes to be committed" in line:
            section = "staged"
            continue
        if "Changes not staged for commit" in line:
            section = "unstaged"
            continue
        if "Untracked files" in line:
            section = "untracked"
            continue
        if "nothing to commit" in line:
            section = "clean"
            continue

        # Skip hint lines (indented instructions)
        if (
            stripped.startswith("(use ")
            or stripped.startswith("(no commit")
            or stripped.startswith("nothing added")
        ):
            continue

        # Skip empty lines
        if not stripped:
            continue

        # Skip "no changes added" boilerplate
        if "no changes added to commit" in line:
            continue

        # Parse file entries within sections
        if section in ("staged", "unstaged") and (
            line.startswith("\t")
            or (len(line) > 1 and line[0] == " " and line[1] == " ")
        ):
            entry = stripped
            # Skip parenthesized hint lines (e.g. "(commit or discard...)")
            if entry.startswith("("):
                continue
            if section == "staged":
                staged.append(entry)
            else:
                unstaged.append(entry)
            continue

        if section == "untracked" and (
            line.startswith("\t")
            or (len(line) > 1 and line[0] == " " and line[1] == " ")
        ):
            entry = stripped
            # Skip hint lines in untracked section
            if not entry.startswith("("):
                untracked.append(entry)

    # Build compressed output
    parts: list[str] = [f"branch: {branch}"]
    if ahead_behind:
        parts[0] += f" ({ahead_behind})"

    if staged:
        parts.append(_format_file_list("staged", staged))
    if unstaged:
        parts.append(_format_file_list("unstaged", unstaged))
    if untracked:
        parts.append(_format_file_list("untracked", untracked))

    if not staged and not unstaged and not untracked:
        parts.append("clean")

    return "\n".join(parts)


def _format_file_list(label: str, files: list[str]) -> str:
    """Format a file list with count, first N files, and overflow indicator.

    Args:
        label: Section label (e.g. "staged", "untracked").
        files: List of file entries.

    Returns:
        Formatted string like "staged (3): file1, file2, file3"
        or "untracked (25): file1, ..., file10, ... [+15 more]"
    """
    count = len(files)
    shown = files[:_MAX_LIST_ITEMS]
    extra = count - len(shown)
    summary = ", ".join(shown)
    if extra > 0:
        summary += f", ... [+{extra} more]"
    return f"{label} ({count}): {summary}"


def filter_git_diff(output: str, command: str, exit_code: int | None) -> str:
    """Compress git diff output.

    Strategy:
    1. Detect format: unified diff (diff --git ...) vs stat-only output.
    2. For stat-only (git diff --stat): extract stat table + summary line.
    3. For unified diff: extract stat lines if present, then show hunk header
       + first N changed lines per file (+ and - lines only, no context).
    4. Fallback: list changed filenames.

    This ensures the model knows WHAT changed, not just THAT something changed.
    """
    lines = output.split("\n")

    # --- Detect format ---
    has_unified_diff = any(line.startswith("diff --git ") for line in lines)

    # --- Extract stat lines (present in git diff --stat or appended to unified diff) ---
    stat_lines: list[str] = []
    for line in lines:
        if re.match(r"^\s+\S.*\|\s+\d+", line):  # " file.py | 5 ++-"
            stat_lines.append(line.strip())
        elif re.match(r"^\d+ files? changed", line):  # "2 files changed, +42/-3"
            stat_lines.append(line.strip())

    # --- Pure --stat output (no unified diff blobs) ---
    if stat_lines and not has_unified_diff:
        return "\n".join(stat_lines)

    # --- Parse unified diff: extract per-file hunks ---
    file_sections: list[tuple[str, list[str]]] = []
    current_file: str | None = None
    current_changes: list[str] = []

    for line in lines:
        if line.startswith("diff --git "):
            # Save previous file
            if current_file is not None:
                file_sections.append((current_file, current_changes))
            m = re.match(r"diff --git a/(.+) b/", line)
            current_file = m.group(1) if m else line[len("diff --git ") :]
            current_changes = []
        elif current_file is not None:
            # Skip index/--- /+++ header lines
            if re.match(r"^(index |--- |\+\+\+ |Binary files)", line):
                continue
            # Hunk headers (@@ -N,M +P,Q @@ context)
            if line.startswith("@@"):
                m = re.match(r"(@@ .+? @@)", line)
                if m and len(current_changes) < _MAX_HUNK_LINES_PER_FILE:
                    current_changes.append(m.group(1))
            # Added lines
            elif (
                line.startswith("+") and len(current_changes) < _MAX_HUNK_LINES_PER_FILE
            ):
                current_changes.append(line[:120])
            # Removed lines
            elif (
                line.startswith("-") and len(current_changes) < _MAX_HUNK_LINES_PER_FILE
            ):
                current_changes.append(line[:120])
            # Context lines: skip (they add noise without adding insight)

    # Flush last file
    if current_file is not None:
        file_sections.append((current_file, current_changes))

    # --- Build result ---
    result_parts: list[str] = []

    # Stat summary first (if available)
    if stat_lines:
        result_parts.extend(stat_lines)

    # Per-file change samples
    total_lines = len(result_parts)
    files_shown = 0
    for filename, changes in file_sections[:_MAX_FILES_WITH_HUNKS]:
        if total_lines >= _MAX_TOTAL_DIFF_LINES:
            break
        if changes:
            result_parts.append(f"\n@@ {filename}")
            for cl in changes[:_MAX_HUNK_LINES_PER_FILE]:
                result_parts.append(cl)
                total_lines += 1
            files_shown += 1

    remaining = len(file_sections) - files_shown
    if remaining > 0:
        result_parts.append(f"... [{remaining} more file(s) not shown]")

    if result_parts:
        return "\n".join(result_parts)

    # --- Fallback: no stat lines, no unified diff blobs → just list filenames ---
    if file_sections:
        names = [f for f, _ in file_sections]
        shown_names = names[:5]
        extra = len(names) - len(shown_names)
        summary = ", ".join(shown_names)
        if extra > 0:
            summary += f", ... [+{extra} more]"
        return f"{len(names)} file(s) changed: {summary}"

    # Last resort: first 300 chars
    return output[:300]


def filter_git_log(output: str, command: str, exit_code: int | None) -> str:
    """Compress git log output.

    Strategy: one-line-per-commit format (hash + subject), strip everything else.
    Works on standard multi-line git log output.
    """
    lines = output.split("\n")
    result_lines: list[str] = []

    current_hash = ""
    current_subject = ""

    for line in lines:
        # New commit block starts with "commit <hash>"
        if line.startswith("commit "):
            if current_hash and current_subject:
                result_lines.append(f"{current_hash[:7]} {current_subject}")
            current_hash = line[7:].strip()
            current_subject = ""
            continue

        # Skip Author:, Date:, Merge: lines
        if re.match(r"^(Author|Date|Merge|AuthorDate|CommitDate|Commit):", line):
            continue

        # Subject line is the first non-empty indented line after commit block
        if current_hash and not current_subject and line.startswith("    "):
            current_subject = line.strip()
            continue

        # Already-formatted one-line log (e.g. git log --oneline)
        if re.match(r"^[0-9a-f]{7,40} \S", line):
            result_lines.append(line.strip())
            continue

    # Flush last commit
    if current_hash and current_subject:
        result_lines.append(f"{current_hash[:7]} {current_subject}")

    return "\n".join(result_lines) if result_lines else output


def filter_git_simple(output: str, command: str, exit_code: int | None) -> str:
    """Compress git push/pull/add/commit output.

    Strategy: success short-circuit — return "ok" when exit code is 0.
    On failure, keep only error/relevant lines.
    """
    # Success: collapse to "ok"
    if exit_code == 0:
        # Extract any meaningful single-line summaries
        lines = output.strip().split("\n")
        useful = []
        for line in lines:
            stripped = line.strip()
            # Keep branch/remote references and counts
            if any(
                kw in stripped
                for kw in [
                    "->",
                    "branch",
                    "files changed",
                    "insertion",
                    "deletion",
                    "create mode",
                    "Unpacking",
                    "Already",
                    "Everything up-to-date",
                ]
            ):
                useful.append(stripped)
        if useful:
            return "\n".join(useful)
        return "ok"

    # Failure: keep error lines
    lines = output.split("\n")
    error_lines = [
        line
        for line in lines
        if line.strip()
        and any(
            kw in line.lower()
            for kw in [
                "error",
                "fatal",
                "rejected",
                "denied",
                "fail",
                "hint",
                "remote:",
            ]
        )
    ]
    return "\n".join(error_lines) if error_lines else output
