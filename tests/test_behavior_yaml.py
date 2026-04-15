"""Tests for the behaviors/compact.yaml bundle descriptor.

Validates that the file is syntactically valid YAML and contains
all the expected structural elements and configuration keys.
"""

from __future__ import annotations

from pathlib import Path

import yaml

BEHAVIORS_DIR = Path(__file__).parent.parent / "behaviors"
COMPACT_YAML = BEHAVIORS_DIR / "compact.yaml"


def _load() -> dict:
    """Load behaviors/compact.yaml as a Python dict."""
    with open(COMPACT_YAML) as f:
        return yaml.safe_load(f)


class TestCompactYamlStructure:
    def test_file_exists(self) -> None:
        """behaviors/compact.yaml must be present."""
        assert COMPACT_YAML.exists(), "behaviors/compact.yaml not found"

    def test_is_valid_yaml(self) -> None:
        """behaviors/compact.yaml must parse without errors."""
        data = _load()
        assert data is not None
        assert isinstance(data, dict)

    def test_has_hooks_key(self) -> None:
        """Top-level 'hooks' key must be present and non-empty."""
        data = _load()
        hooks = data.get("hooks")
        assert hooks is not None, "Missing 'hooks' key"
        assert isinstance(hooks, list)
        assert len(hooks) > 0, "hooks list is empty"

    def test_hook_module_is_hooks_compact(self) -> None:
        """The hook entry must specify module='hooks-compact'."""
        data = _load()
        hooks = data["hooks"]
        modules = [h.get("module") for h in hooks]
        assert "hooks-compact" in modules


class TestCompactYamlSourceUrl:
    def test_source_url_contains_samueljklee(self) -> None:
        """The source URL must reference the samueljklee GitHub account."""
        content = COMPACT_YAML.read_text()
        assert "samueljklee" in content, (
            "Expected 'samueljklee' in source URL but it was not found"
        )

    def test_source_url_is_git_url(self) -> None:
        """The source field must be a git+ URL pointing to the correct repo."""
        content = COMPACT_YAML.read_text()
        assert "git+" in content
        assert "amplifier-module-hooks-compact" in content


class TestCompactYamlConfigKeys:
    def _config(self) -> dict:
        data = _load()
        return data["hooks"][0]["config"]

    def test_enabled_key_present(self) -> None:
        """config.enabled must be declared."""
        assert "enabled" in self._config()

    def test_min_lines_key_present(self) -> None:
        """config.min_lines must be declared."""
        assert "min_lines" in self._config()

    def test_strip_ansi_key_present(self) -> None:
        """config.strip_ansi must be declared."""
        assert "strip_ansi" in self._config()

    def test_show_savings_key_present(self) -> None:
        """config.show_savings must be declared."""
        assert "show_savings" in self._config()

    def test_debug_key_present(self) -> None:
        """config.debug must be declared."""
        assert "debug" in self._config()

    def test_telemetry_block_present(self) -> None:
        """config.telemetry sub-block must be declared."""
        config = self._config()
        assert "telemetry" in config
        telemetry = config["telemetry"]
        assert isinstance(telemetry, dict)

    def test_telemetry_has_local_key(self) -> None:
        """config.telemetry.local must be declared."""
        telemetry = self._config()["telemetry"]
        assert "local" in telemetry

    def test_default_enabled_is_true(self) -> None:
        """config.enabled defaults to True in the shipped behavior."""
        assert self._config()["enabled"] is True

    def test_default_min_lines_is_positive(self) -> None:
        """config.min_lines must be a positive integer."""
        min_lines = self._config()["min_lines"]
        assert isinstance(min_lines, int)
        assert min_lines > 0
