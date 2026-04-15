"""Git command output filters.

Compresses verbose git output using command-specific parsing strategies:
- git status:  strip hints/boilerplate, group by state, show counts
- git diff:    keep diffstat summary + changed hunks, strip context noise
- git log:     one-line-per-commit, strip author/date/stats
- git simple:  success short-circuit (push/pull/add/commit → "ok")
"""

from __future__ import annotations

import re


def filter_git_status(output: str, command: str, exit_code: int | None) -> str:
    """Compress git status output.

    Strategy: strip instructional hints, group by staged/unstaged/untracked,
    show file counts and branch name.

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
        parts.append(f"staged ({len(staged)}): {', '.join(staged)}")
    if unstaged:
        parts.append(f"unstaged ({len(unstaged)}): {', '.join(unstaged)}")
    if untracked:
        parts.append(f"untracked ({len(untracked)}): {', '.join(untracked)}")

    if not staged and not unstaged and not untracked:
        parts.append("clean")

    return "\n".join(parts)


def filter_git_diff(output: str, command: str, exit_code: int | None) -> str:
    """Compress git diff output.

    Strategy: extract only the diffstat summary (filename | N +/- lines).
    Strip context lines and raw diff content.
    """
    lines = output.split("\n")
    result_lines: list[str] = []
    in_stat = False

    for line in lines:
        # Diffstat lines have the pattern: " file | N +++---"
        # The summary line: "N files changed, N insertions(+), N deletions(-)"
        if re.match(r"^\s+\S.*\|\s+\d+", line):
            result_lines.append(line.strip())
            in_stat = True
            continue
        if in_stat and re.match(r"^\d+ file", line):
            result_lines.append(line.strip())
            in_stat = False
            continue

        # For git diff --stat output (no context), just keep stat lines
        if re.match(r"^\s*[\w./\-]+.*\|\s+\d+", line):
            result_lines.append(line.strip())
            continue

        # Keep summary line
        if re.match(r"^\d+ files? changed", line):
            result_lines.append(line.strip())
            continue

    if not result_lines:
        # Fallback: if no diffstat found (e.g. raw diff), show file count summary
        changed_files = set()
        for line in lines:
            m = re.match(r"^diff --git a/(.+) b/", line)
            if m:
                changed_files.add(m.group(1))
            m = re.match(r"^--- a/(.+)", line)
            if m:
                changed_files.add(m.group(1))
        if changed_files:
            result_lines.append(f"{len(changed_files)} file(s) changed")

    return "\n".join(result_lines) if result_lines else output[:200]


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
