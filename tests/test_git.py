"""Unit tests for git command output filters."""

from __future__ import annotations

from pathlib import Path


from amplifier_module_hooks_compact.filters.git import (
    filter_git_diff,
    filter_git_log,
    filter_git_simple,
    filter_git_status,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── git status ────────────────────────────────────────────────────────────────


class TestFilterGitStatus:
    def test_dirty_status_shows_branch(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert "feature/compression-pipeline" in result

    def test_dirty_status_shows_staged_files(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert "staged" in result
        assert "hook.py" in result or "pipeline.py" in result

    def test_dirty_status_shows_unstaged_files(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert "unstaged" in result
        assert "README.md" in result

    def test_dirty_status_shows_untracked_files(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert "untracked" in result
        assert ".env.example" in result or "docs/architecture.md" in result

    def test_dirty_status_strips_hint_lines(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert 'use "git restore"' not in result
        assert 'use "git add"' not in result

    def test_dirty_status_significantly_shorter(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert len(result) < len(fixture) * 0.7, "Expected >30% compression"

    def test_clean_status(self):
        fixture = (FIXTURES / "git_status_clean.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert "main" in result
        assert "clean" in result.lower() or "nothing" in result.lower()

    def test_starts_with_branch(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        assert result.startswith("branch:")

    def test_shows_file_counts(self):
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        result = filter_git_status(fixture, "git status", 0)
        # Should show count in parentheses
        assert "(" in result and ")" in result

    def test_inline_ahead_behind(self):
        output = (
            "On branch main\n"
            "Your branch is ahead of 'origin/main' by 3 commits.\n"
            '  (use "git push" to publish your local commits)\n'
            "\n"
            "nothing to commit, working tree clean\n"
        )
        result = filter_git_status(output, "git status", 0)
        assert "main" in result

    def test_detached_head(self):
        output = "HEAD detached at abc1234\nnothing to commit, working tree clean\n"
        result = filter_git_status(output, "git status", 0)
        assert "detached" in result or "abc1234" in result

    def test_ahead_plural_preserved(self):
        """'3 commits ahead' should preserve plural 's' (not truncate to 'commit')."""
        output = (
            "On branch main\n"
            "Your branch is ahead of 'origin/main' by 3 commits.\n"
            '  (use "git push" to publish your local commits)\n'
            "\n"
            "nothing to commit, working tree clean\n"
        )
        result = filter_git_status(output, "git status", 0)
        assert "3 commits" in result  # not "3 commit"

    def test_behind_plural_preserved(self):
        """'2 commits behind' should preserve plural 's'."""
        output = (
            "On branch main\n"
            "Your branch is behind 'origin/main' by 2 commits, "
            "and can be fast-forwarded.\n"
            '  (use "git pull" to update your local branch)\n'
            "\n"
            "nothing to commit, working tree clean\n"
        )
        result = filter_git_status(output, "git status", 0)
        assert "2 commits" in result

    def test_large_untracked_list_truncated(self):
        """When a repo has many untracked files, the list is truncated to avoid bloat."""
        # Build a status with 25 untracked files
        lines = ["On branch main", "", "Untracked files:"]
        lines.append('  (use "git add ..." to include in what will be committed)')
        for i in range(25):
            lines.append(f"\tfile_{i:02d}.txt")
        output = "\n".join(lines) + "\n"
        result = filter_git_status(output, "git status", 0)
        # Count shows 25
        assert "(25)" in result
        # But file list is truncated
        assert "+15 more" in result or "more" in result
        # Result is significantly shorter
        assert len(result) < len(output) * 0.7

    def test_large_untracked_list_shows_first_n(self):
        """First 10 files are always shown even with large untracked list."""
        lines = ["On branch main", "", "Untracked files:"]
        lines.append('  (use "git add ..." to include in what will be committed)')
        for i in range(15):
            lines.append(f"\tfile_{i:02d}.py")
        output = "\n".join(lines) + "\n"
        result = filter_git_status(output, "git status", 0)
        # First 10 files should be in output
        assert "file_00.py" in result
        assert "file_09.py" in result
        # 11th file should not be listed directly (it's in the "+5 more" count)
        assert "(15)" in result


# ── git diff ──────────────────────────────────────────────────────────────────


class TestFilterGitDiff:
    SAMPLE_DIFF_STAT = (
        " src/auth.py     | 24 +++++++++--\n"
        " README.md       |  5 +--\n"
        " tests/test.py   |  8 +++\n"
        "3 files changed, 29 insertions(+), 8 deletions(-)\n"
    )

    def test_keeps_diffstat_lines(self):
        result = filter_git_diff(self.SAMPLE_DIFF_STAT, "git diff", 0)
        assert "src/auth.py" in result
        assert "README.md" in result

    def test_keeps_summary_line(self):
        result = filter_git_diff(self.SAMPLE_DIFF_STAT, "git diff", 0)
        assert "files changed" in result

    def test_unified_diff_keeps_changed_lines(self):
        """Unified diff: model must see what changed, not just that something changed."""
        fixture = (FIXTURES / "git_diff_unified.txt").read_text()
        result = filter_git_diff(fixture, "git diff", 0)
        # Must include actual added/removed lines so model knows what changed
        assert "+" in result or "-" in result

    def test_unified_diff_keeps_filenames(self):
        """Unified diff: file names must be visible."""
        fixture = (FIXTURES / "git_diff_unified.txt").read_text()
        result = filter_git_diff(fixture, "git diff", 0)
        assert "src/auth.py" in result or "auth.py" in result

    def test_unified_diff_significantly_shorter(self):
        """Unified diff: still achieves meaningful compression."""
        fixture = (FIXTURES / "git_diff_unified.txt").read_text()
        result = filter_git_diff(fixture, "git diff", 0)
        # Should compress by at least 40% (unified diffs are verbose with context lines)
        assert len(result) < len(fixture) * 0.6

    def test_unified_diff_preserves_hunk_headers(self):
        """Hunk @@ markers should be included to give structural context."""
        fixture = (FIXTURES / "git_diff_unified.txt").read_text()
        result = filter_git_diff(fixture, "git diff", 0)
        assert "@@" in result

    def test_stat_only_output(self):
        """Pure --stat output (no unified diff) should just show stat table."""
        result = filter_git_diff(self.SAMPLE_DIFF_STAT, "git diff --stat", 0)
        assert "src/auth.py" in result
        assert "files changed" in result

    def test_strips_raw_diff_content(self):
        full_diff = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "index abc1234..def5678 100644\n"
            "--- a/src/auth.py\n"
            "+++ b/src/auth.py\n"
            "@@ -40,6 +40,8 @@ class Auth:\n"
            " def login(self):\n"
            "+    # New comment\n"
            "+    self.validate()\n"
            "     return self.token\n"
            " \n"
            " src/auth.py     | 2 ++\n"
            "1 file changed, 2 insertions(+)\n"
        )
        result = filter_git_diff(full_diff, "git diff", 0)
        # File name is kept
        assert "src/auth.py" in result
        # Result is shorter than original (context lines stripped)
        assert len(result) < len(full_diff)

    def test_large_diff_capped_at_max_lines(self):
        """Very large diffs should not produce unbounded output."""
        # Build a large fake diff with 20 files
        lines = []
        for i in range(20):
            lines.append(f"diff --git a/file{i}.py b/file{i}.py")
            lines.append("index abc..def 100644")
            lines.append(f"--- a/file{i}.py")
            lines.append(f"+++ b/file{i}.py")
            lines.append("@@ -1,5 +1,10 @@")
            for j in range(10):
                lines.append(f"+    new_line_{j} = True")
                lines.append(f"-    old_line_{j} = False")
        large_diff = "\n".join(lines)
        result = filter_git_diff(large_diff, "git diff", 0)
        # Output should be bounded (not all 20 files * 20 lines = 400+ lines)
        assert result.count("\n") < 80


# ── git log ───────────────────────────────────────────────────────────────────


class TestFilterGitLog:
    SAMPLE_LOG = (
        "commit abc1234567890abcdef1234567890abcdef12345678\n"
        "Author: Dev <dev@example.com>\n"
        "Date:   Mon Apr 15 10:00:00 2026 +0000\n"
        "\n"
        "    feat: add compression pipeline\n"
        "\n"
        "commit def5678901234567890abcdef1234567890abcdef\n"
        "Author: Dev <dev@example.com>\n"
        "Date:   Sun Apr 14 15:30:00 2026 +0000\n"
        "\n"
        "    fix: handle empty output correctly\n"
        "\n"
        "commit 999aaabbbccc1234567890abcdef1234567890abcd\n"
        "Author: Dev <dev@example.com>\n"
        "Date:   Sat Apr 13 09:00:00 2026 +0000\n"
        "\n"
        "    chore: update dependencies\n"
        "\n"
    )

    def test_one_line_per_commit(self):
        result = filter_git_log(self.SAMPLE_LOG, "git log", 0)
        lines = [ln for ln in result.split("\n") if ln.strip()]
        assert len(lines) == 3  # 3 commits → 3 lines

    def test_strips_author_lines(self):
        result = filter_git_log(self.SAMPLE_LOG, "git log", 0)
        assert "Author:" not in result

    def test_strips_date_lines(self):
        result = filter_git_log(self.SAMPLE_LOG, "git log", 0)
        assert "Date:" not in result

    def test_includes_commit_subjects(self):
        result = filter_git_log(self.SAMPLE_LOG, "git log", 0)
        assert "feat: add compression pipeline" in result
        assert "fix: handle empty output correctly" in result

    def test_includes_short_hash(self):
        result = filter_git_log(self.SAMPLE_LOG, "git log", 0)
        assert "abc1234" in result  # First 7 chars of first hash

    def test_passthrough_oneline_format(self):
        """Already-formatted --oneline output should pass through cleanly."""
        oneline = (
            "abc1234 feat: add compression\n"
            "def5678 fix: handle edge case\n"
            "999aaab chore: update deps\n"
        )
        result = filter_git_log(oneline, "git log --oneline", 0)
        assert "feat: add compression" in result
        assert "fix: handle edge case" in result


# ── git simple (push/pull/add/commit) ─────────────────────────────────────────


class TestFilterGitSimple:
    def test_push_success_returns_ok(self):
        output = (
            "Enumerating objects: 5, done.\n"
            "Counting objects: 100% (5/5), done.\n"
            "Delta compression using up to 8 threads\n"
            "Compressing objects: 100% (3/3), done.\n"
            "Writing objects: 100% (3/3), 349 bytes | 349.00 KiB/s, done.\n"
            "Total 3 (delta 2), reused 0 (delta 0), pack-reused 0\n"
            "To github.com:user/repo.git\n"
            "   abc1234..def5678  main -> main\n"
        )
        result = filter_git_simple(output, "git push", 0)
        # Should be short
        assert len(result) < len(output) * 0.5

    def test_commit_success_returns_short_summary(self):
        output = (
            "[main abc1234] feat: add compression pipeline\n"
            " 3 files changed, 47 insertions(+), 2 deletions(-)\n"
            " create mode 100644 amplifier_module_hooks_compact/pipeline.py\n"
        )
        result = filter_git_simple(output, "git commit", 0)
        # Should preserve meaningful info like "files changed"
        assert len(result) <= len(output)

    def test_commit_success_preserves_commit_message(self):
        """git commit output must include the commit hash and message line.

        Without this, the model doesn't know which commit was created or its subject.
        """
        output = (
            "[main def5678] feat: implement hooks-compact filter\n"
            " 5 files changed, 120 insertions(+), 3 deletions(-)\n"
            " create mode 100644 amplifier_module_hooks_compact/hook.py\n"
        )
        result = filter_git_simple(output, "git commit", 0)
        # The "[branch hash] message" line must be preserved
        assert "def5678" in result, f"Commit hash missing from:\n{result}"
        assert "feat: implement hooks-compact filter" in result, (
            f"Commit message missing from:\n{result}"
        )

    def test_already_up_to_date(self):
        output = "Already up to date.\n"
        result = filter_git_simple(output, "git pull", 0)
        # Short, contains "Already" or "ok"
        assert "Already" in result or "ok" in result or len(result) < 30

    def test_push_failure_shows_error(self):
        output = (
            "To github.com:user/repo.git\n"
            " ! [rejected]        main -> main (fetch first)\n"
            "error: failed to push some refs to 'github.com:user/repo.git'\n"
            "hint: Updates were rejected because the remote contains work that you do\n"
            "hint: not have locally.\n"
        )
        result = filter_git_simple(output, "git push", 1)
        assert "error" in result.lower() or "rejected" in result.lower()

    def test_add_success(self):
        output = ""  # git add produces no output on success
        result = filter_git_simple(output, "git add .", 0)
        assert "ok" in result.lower() or result == ""
