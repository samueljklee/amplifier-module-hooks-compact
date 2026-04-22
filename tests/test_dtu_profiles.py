"""Tests for DTU eval profile URI correctness.

Ensures hooks-compact-with.yaml references the pinned canary tag rather than
@main so that Container A tests the tagged release, not the moving main branch.
"""

from __future__ import annotations

from pathlib import Path

EVAL_PROFILES_DIR = Path(__file__).parent.parent / "eval" / "profiles"
WITH_PROFILE = EVAL_PROFILES_DIR / "hooks-compact-with.yaml"
WITHOUT_PROFILE = EVAL_PROFILES_DIR / "hooks-compact-without.yaml"

CANARY_TAG = "v0.1.0-canary.1"
OWN_REPO = "samueljklee/amplifier-module-hooks-compact"


class TestDTUProfileURIs:
    """DTU Container A profile must reference the canary tag, not @main."""

    def test_with_profile_has_no_main_ref_for_own_repo(self):
        """hooks-compact-with.yaml must not reference own repo at @main."""
        content = WITH_PROFILE.read_text()
        assert f"{OWN_REPO}@main" not in content, (
            f"hooks-compact-with.yaml still references {OWN_REPO}@main; "
            f"update both URIs to @{CANARY_TAG} before launching the DTU."
        )

    def test_with_profile_has_canary_tag_in_bundle_added(self):
        """bundle.added entry must reference the canary tag."""
        content = WITH_PROFILE.read_text()
        assert f"behavior-compact: git+https://github.com/{OWN_REPO}@{CANARY_TAG}#subdirectory=behaviors/compact.yaml" in content

    def test_with_profile_has_canary_tag_in_bundle_app(self):
        """bundle.app entry must reference the canary tag."""
        content = WITH_PROFILE.read_text()
        assert f"- git+https://github.com/{OWN_REPO}@{CANARY_TAG}#subdirectory=behaviors/compact.yaml" in content

    def test_canary_uri_appears_exactly_twice(self):
        """Exactly two canary URIs expected — bundle.added and bundle.app."""
        content = WITH_PROFILE.read_text()
        count = content.count(f"{OWN_REPO}@{CANARY_TAG}")
        assert count == 2, f"Expected 2 canary URI occurrences, found {count}"

    def test_without_profile_untouched(self):
        """hooks-compact-without.yaml must not reference own repo at all."""
        content = WITHOUT_PROFILE.read_text()
        assert OWN_REPO not in content, (
            "hooks-compact-without.yaml should not reference the own repo; "
            "the B-side baseline has no hooks-compact bundle entries."
        )
