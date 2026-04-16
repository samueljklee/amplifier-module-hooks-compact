"""Filter registry for command classification and routing.

Lookup priority (first match wins):
1. User-project YAML filters (.amplifier/output-filters.yaml)
2. User-global YAML filters   (~/.amplifier/output-filters.yaml)
3. Built-in Python filters     (git, pytest, cargo test, etc.)
4. Built-in YAML filters       (make, docker, pip, etc.)
5. Passthrough                  (no match)
"""

from __future__ import annotations

import re
from typing import Any, Callable

# Type alias for Python filter functions:
#   (output: str, command: str, exit_code: int | None) -> str
PythonFilter = Callable[[str, str, "int | None"], str]


# Matches one or more leading "cd /some/path &&" or "cd /some/path;" segments
# so classify() can strip them before pattern matching.
# Examples that are stripped:
#   "cd /foo &&"      "cd /foo;"     "cd /a && cd /b &&"
_CD_PREFIX_RE = re.compile(r"^(?:cd\s+\S+\s*(?:&&|;)\s*)+")


def _strip_shell_prefix(command: str) -> str:
    """Strip leading cd-directory-change segments from a shell command string.

    Amplifier's bash tool frequently prepends ``cd /path &&`` before the
    real command.  Stripping those prefixes lets filter patterns that are
    anchored with ``^`` (e.g. ``^git\\s+status``) match correctly.

    Args:
        command: The raw bash command string, possibly containing ``cd`` prefixes.

    Returns:
        The command with any leading ``cd /path &&`` / ``cd /path;`` segments
        removed.  Returns the original string unchanged when no prefix is found.
    """
    return _CD_PREFIX_RE.sub("", command)


class FilterRegistry:
    """Registry of command-to-filter mappings.

    Maintains three priority buckets:
    - user_yaml: highest priority (user-defined YAML overrides)
    - python: built-in Python filters (complex parsing)
    - yaml: built-in YAML filters (simple regex pipelines)
    """

    def __init__(self) -> None:
        # (name, compiled_pattern, config_dict)
        self._user_yaml_filters: list[tuple[str, re.Pattern[str], dict[str, Any]]] = []
        # (name, compiled_pattern, filter_fn)
        self._python_filters: list[tuple[str, re.Pattern[str], PythonFilter]] = []
        # (name, compiled_pattern, config_dict)
        self._yaml_filters: list[tuple[str, re.Pattern[str], dict[str, Any]]] = []

    def register_user_yaml(
        self, name: str, command_pattern: str, config: dict[str, Any]
    ) -> None:
        """Register a user-defined YAML filter with highest priority.

        Args:
            name: Filter identifier.
            command_pattern: Regex to match against the bash command string.
            config: YAML filter configuration dict.
        """
        self._user_yaml_filters.append((name, re.compile(command_pattern), config))

    def register_python(
        self, name: str, command_pattern: str, filter_fn: PythonFilter
    ) -> None:
        """Register a built-in Python filter function.

        Args:
            name: Filter identifier.
            command_pattern: Regex to match against the bash command string.
            filter_fn: Filter callable (output, command, exit_code) -> str.
        """
        self._python_filters.append((name, re.compile(command_pattern), filter_fn))

    def register_yaml(self, name: str, config: dict[str, Any]) -> None:
        """Register a built-in YAML filter configuration.

        The config dict must contain a 'match_command' key with a regex pattern.

        Args:
            name: Filter identifier (typically the yaml file stem).
            config: YAML filter configuration dict containing 'match_command'.
        """
        match_pattern = config.get("match_command", "")
        if not match_pattern:
            return
        self._yaml_filters.append((name, re.compile(match_pattern), config))

    def classify(
        self, command: str
    ) -> tuple[str, PythonFilter | dict[str, Any]] | None:
        """Classify a command and return its matching filter.

        Checks priority buckets in order: user YAML → Python → built-in YAML.
        First match wins.

        Strips leading ``cd /path &&`` / ``cd /path;`` shell prefixes before
        matching so that patterns anchored with ``^`` (e.g. ``^git\\s+status``)
        work correctly even when Amplifier's bash tool prepends a directory
        change to the command string.

        Args:
            command: The bash command string to classify.

        Returns:
            Tuple of (filter_name, filter_fn_or_config) if matched, None otherwise.
            If filter_fn_or_config is callable, it's a Python filter.
            If it's a dict, it's a YAML filter config.
        """
        # Strip "cd /path &&" / "cd /path;" prefixes before matching so that
        # anchored patterns (^git, ^cargo, …) are not defeated by the directory
        # change that Amplifier's bash tool prepends.
        matchable = _strip_shell_prefix(command)

        # Priority 1: User YAML filters (project-local or user-global)
        for name, pattern, config in self._user_yaml_filters:
            if pattern.search(matchable):
                return (name, config)

        # Priority 2: Built-in Python filters
        for name, pattern, filter_fn in self._python_filters:
            if pattern.search(matchable):
                return (name, filter_fn)

        # Priority 3: Built-in YAML filters
        for name, pattern, config in self._yaml_filters:
            if pattern.search(matchable):
                return (name, config)

        return None
