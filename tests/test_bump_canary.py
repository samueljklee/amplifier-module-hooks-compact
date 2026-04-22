"""Tests for scripts/bump-canary.sh.

Covers: help flag, tag-format validation, dry-run safety, and current-tag
detection from behaviors/compact.yaml.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bump-canary.sh"


def run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run bump-canary.sh with the given args, capturing stdout + stderr."""
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


class TestBumpCanary:
    def test_help_flag_exits_zero(self):
        """--help exits 0 and prints usage containing the '<new-tag>' placeholder."""
        result = run_script(["--help"])
        assert result.returncode == 0
        assert "<new-tag>" in result.stdout

    def test_invalid_tag_format_rejected(self):
        """Tags missing the -canary.N suffix exit non-zero with an error message."""
        result = run_script(["v0.1.0"])
        assert result.returncode != 0
        # A clear error should be emitted on stderr (or at minimum somewhere)
        assert (result.stderr + result.stdout).strip()

    def test_dry_run_no_changes(self):
        """--dry-run --no-push exits 0, leaves working tree clean, creates no tag."""
        # Pre-condition: working tree must be clean before this test runs
        pre = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=str(REPO_ROOT),
        )
        assert pre.returncode == 0, "Test requires a clean working tree"

        result = run_script(["v0.1.0-canary.999", "--dry-run", "--no-push"])
        assert result.returncode == 0

        # Working tree must still be clean
        post = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=str(REPO_ROOT),
        )
        assert post.returncode == 0, "Working tree should be clean after --dry-run"

        # The test tag must NOT have been created
        tags = subprocess.run(
            ["git", "tag", "-l", "v0.1.0-canary.999"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "v0.1.0-canary.999" not in tags.stdout

    def test_detects_current_tag_from_behaviors_yaml(self):
        """Dry-run reports v0.1.0-canary.1 as the current tag (read from behaviors/compact.yaml)."""
        result = run_script(["v0.1.0-canary.2", "--dry-run", "--no-push"])
        assert result.returncode == 0
        assert "v0.1.0-canary.1" in result.stdout
