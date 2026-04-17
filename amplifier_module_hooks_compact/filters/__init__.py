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


# Matches one or more leading "cd /some/path &&" or "cd /some/path;" segments.
# Examples that are stripped:
#   "cd /foo &&"      "cd /foo;"     "cd /a && cd /b &&"
_CD_PREFIX_RE = re.compile(r"^(?:cd\s+\S+\s*(?:&&|;)\s*)+")

# Matches tool-runner prefixes that wrap the real command.
# These are stripped so filter patterns anchored with '^' work correctly.
# Examples:
#   "uvx ruff check ."           -> "ruff check ."
#   "uv run pytest -v"           -> "pytest -v"
#   "npx eslint src/"            -> "eslint src/"
#   "poetry run pytest"          -> "pytest"
#   "python -m pytest"           -> "pytest"
#   "python3 -m ruff check ."    -> "ruff check ."
#   "bunx vitest run"            -> "vitest run"
_TOOL_RUNNER_RE = re.compile(
    r"^(?:"
    r"uvx\s+"  # uv tool runner: uvx ruff check
    r"|uv\s+run\s+"  # uv project runner: uv run pytest
    r"|npx\s+"  # npm package runner: npx eslint
    r"|bunx\s+"  # bun package runner: bunx vitest
    r"|poetry\s+run\s+"  # poetry runner: poetry run pytest
    r"|pnpm\s+(?:exec\s+|dlx\s+)?"  # pnpm runners: pnpm exec / pnpm dlx
    r"|yarn\s+(?:exec\s+|dlx\s+)?"  # yarn runners: yarn exec / yarn dlx
    r"|python3?\s+-m\s+"  # module runner: python -m pytest / python3 -m ruff
    r")"
)


def _strip_shell_prefix(command: str) -> str:
    """Strip leading shell prefixes from a command string before classification.

    Handles two kinds of prefixes that Amplifier's bash tool frequently adds:

    1. **Directory changes**: ``cd /path &&`` / ``cd /path;`` segments.
    2. **Tool runners**: ``uvx``, ``uv run``, ``npx``, ``poetry run``,
       ``python -m``, ``bunx``, ``pnpm exec``, ``yarn dlx``, etc.

    Stripping these prefixes lets filter patterns that are anchored with
    ``^`` (e.g. ``^git``, ``^ruff``, ``^pytest``) match correctly even when
    the model invokes a command through a runner or from a different directory.

    Args:
        command: The raw bash command string.

    Returns:
        The command with any leading directory-change and/or tool-runner
        segments removed.  Returns the original string unchanged when no
        strippable prefix is found.

    Examples:
        >>> _strip_shell_prefix("cd /repo && uvx ruff check .")
        "ruff check ."
        >>> _strip_shell_prefix("uv run pytest -v")
        "pytest -v"
        >>> _strip_shell_prefix("npx eslint src/")
        "eslint src/"
        >>> _strip_shell_prefix("git status")
        "git status"
    """
    # First strip cd-prefix chains (may appear before or without a runner)
    after_cd = _CD_PREFIX_RE.sub("", command)
    # Then strip a single tool-runner prefix if present
    after_runner = _TOOL_RUNNER_RE.sub("", after_cd)
    return after_runner


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

        Strips leading shell prefixes before matching so that patterns anchored
        with ``^`` (e.g. ``^git``, ``^ruff``, ``^pytest``) work correctly even
        when Amplifier's bash tool prepends directory changes or the model uses
        a tool runner.  Two kinds of prefixes are stripped:

        - **Directory changes**: ``cd /path &&`` / ``cd /path;`` chains.
        - **Tool runners**: ``uvx``, ``uv run``, ``npx``, ``poetry run``,
          ``python -m``, ``bunx``, ``pnpm exec``, ``yarn dlx``.

        Compound commands (containing ``&&`` or `` ; `` after stripping) are
        **not compressed**.  Applying a single-command filter to the combined
        output of e.g. ``git status && git log && git diff`` strips the log and
        diff output, leaving the model with only the status summary and causing
        it to retry the missing commands — adding extra tool calls rather than
        saving them.

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

        # Guard: if the command is a genuine compound command after stripping
        # shell prefixes, skip all filters and return passthrough.  Applying a
        # single-command filter to combined multi-command output would silently
        # strip the output of the later commands, causing the model to retry.
        # Examples that would be incorrectly filtered without this guard:
        #   "git status && git log --oneline -10 && git diff"
        #   "cd /repo && git status && git diff"  (after cd-strip: "git status && git diff")
        #   "git status --porcelain | grep '^??'"  (pipe changes the output format)
        if "&&" in matchable or " ; " in matchable or " | " in matchable:
            return None

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
