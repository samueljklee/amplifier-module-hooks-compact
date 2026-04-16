"""Core hook handler: classify -> preprocess -> filter -> decide pipeline.

This is the heart of hooks-compact. Every bash tool result flows through
the 4-stage pipeline defined here.

Fail-safe: any exception at any stage returns HookResult(action="continue"),
preserving the raw output unchanged.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

try:
    from amplifier_core.models import HookResult  # type: ignore[import-untyped]
except ImportError:

    class HookResult:  # type: ignore[no-redef]
        """Minimal HookResult fallback for standalone/test environments."""

        def __init__(self, action: str = "continue", **kwargs: Any) -> None:
            self.action = action
            self.data: dict[str, Any] | None = None
            self.user_message: str | None = None
            self.user_message_level: str | None = None
            for k, v in kwargs.items():
                setattr(self, k, v)


from .filters import FilterRegistry, _strip_shell_prefix
from .pipeline import preprocess

logger = logging.getLogger(__name__)

_CONTINUE = HookResult(action="continue")


class CompactHook:
    """Bash output compression hook.

    4-stage pipeline:
      1. CLASSIFY  — is this bash? match against registered filters.
      2. PRE-PROCESS — strip ANSI, collapse blanks, truncate long lines.
      3. FILTER    — apply command-specific filter (Python or YAML).
      4. DECIDE    — return modified result or passthrough.

    Fail-safe: any exception → return continue (raw output unchanged).
    Never mutates data in-place — always deep-copies before modification.
    """

    def __init__(
        self,
        config: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        self.enabled: bool = config.get("enabled", True)
        self.min_lines: int = int(config.get("min_lines", 5))
        self.strip_ansi: bool = config.get("strip_ansi", True)
        self.show_savings: bool = config.get("show_savings", True)
        self.debug: bool = config.get("debug", False)
        self._session_id: str = session_id or "unknown"

        # Telemetry (optional)
        self._telemetry = None
        telemetry_cfg = config.get("telemetry") or {}
        if telemetry_cfg.get("local", True):
            try:
                from .telemetry import TelemetryStore

                self._telemetry = TelemetryStore(telemetry_cfg)
            except Exception as e:
                logger.warning(f"hooks-compact: Failed to init telemetry: {e}")

        # Filter registry
        self._registry = FilterRegistry()
        self._register_builtin_filters()
        self._load_user_yaml_filters()

    # ── Filter registration ────────────────────────────────────────────────────

    def _register_builtin_filters(self) -> None:
        """Register all built-in Python and YAML filters."""
        try:
            from .filters import git, test_runners, build, lint

            # ── Git filters ───────────────────────────────────────────────────
            self._registry.register_python(
                "git-status", r"^git\s+status\b", git.filter_git_status
            )
            self._registry.register_python(
                "git-diff", r"^git\s+diff\b", git.filter_git_diff
            )
            self._registry.register_python(
                "git-log", r"^git\s+log\b", git.filter_git_log
            )
            # push/pull/add/commit short-circuit
            self._registry.register_python(
                "git-simple",
                r"^git\s+(push|pull|add|commit)\b",
                git.filter_git_simple,
            )

            # ── Test runner filters ───────────────────────────────────────────
            self._registry.register_python(
                "cargo-test", r"^cargo\s+test\b", test_runners.filter_cargo_test
            )
            self._registry.register_python(
                "pytest",
                r"^(python[23]?(?:\.[0-9]+)?\s+-m\s+)?pytest\b"
                r"|^uv\s+run\s+pytest\b"
                r"|^poetry\s+run\s+pytest\b",
                test_runners.filter_pytest,
            )
            self._registry.register_python(
                "npm-test",
                # Matches npm test / npm run test directly, plus standalone
                # vitest and jest invocations (the tool-runner prefix is
                # stripped by _strip_shell_prefix before this is evaluated,
                # so "bunx vitest run" becomes "vitest run" here).
                r"^npm\s+(test|run\s+test)\b|^vitest\b|^jest\b",
                test_runners.filter_npm_test,
            )

            # ── Build filters ─────────────────────────────────────────────────
            self._registry.register_python(
                "cargo-build", r"^cargo\s+build\b", build.filter_cargo_build
            )
            self._registry.register_python("tsc", r"^(npx\s+)?tsc\b", build.filter_tsc)
            self._registry.register_python(
                "npm-build", r"^npm\s+run\s+build\b", build.filter_npm_build
            )

            # ── Lint filters ──────────────────────────────────────────────────
            self._registry.register_python(
                "cargo-clippy", r"^cargo\s+clippy\b", lint.filter_cargo_clippy
            )
            self._registry.register_python(
                "ruff",
                r"^(uv\s+run\s+)?ruff\s+check\b",
                lint.filter_ruff,
            )
            self._registry.register_python(
                "eslint", r"^(npx\s+)?eslint\b", lint.filter_eslint
            )

        except ImportError as e:
            logger.warning(f"hooks-compact: Failed to import Python filters: {e}")

        # Load built-in YAML filters
        self._load_builtin_yaml_filters()

    def _load_builtin_yaml_filters(self) -> None:
        """Load built-in YAML filters from the builtin_filters/ directory."""
        try:
            import yaml
        except ImportError:
            logger.warning("hooks-compact: pyyaml not available, skipping YAML filters")
            return

        builtin_dir = Path(__file__).parent / "builtin_filters"
        if not builtin_dir.exists():
            return

        for yaml_file in sorted(builtin_dir.glob("*.yaml")):
            filter_name = yaml_file.stem
            try:
                with open(yaml_file) as f:
                    config = yaml.safe_load(f)
                if config and isinstance(config, dict):
                    self._registry.register_yaml(filter_name, config)
                    logger.debug(
                        f"hooks-compact: Loaded builtin YAML filter '{filter_name}'"
                    )
            except Exception as e:
                logger.warning(
                    f"hooks-compact: Failed to load builtin filter {yaml_file.name}: {e}"
                )

    def _load_user_yaml_filters(self) -> None:
        """Load user-defined YAML filters with highest priority.

        Checks in order:
        1. .amplifier/output-filters.yaml  (project-local)
        2. ~/.amplifier/output-filters.yaml (user-global)
        """
        try:
            import yaml
        except ImportError:
            return

        search_paths = [
            Path.cwd() / ".amplifier" / "output-filters.yaml",
            Path.home() / ".amplifier" / "output-filters.yaml",
        ]

        for yaml_path in search_paths:
            if not yaml_path.exists():
                continue
            try:
                with open(yaml_path) as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue
                for filter_name, filter_config in data.items():
                    if not isinstance(filter_config, dict):
                        continue
                    match_cmd = filter_config.get("match_command")
                    if match_cmd:
                        self._registry.register_user_yaml(
                            filter_name, match_cmd, filter_config
                        )
                        logger.debug(
                            f"hooks-compact: Loaded user YAML filter '{filter_name}' "
                            f"from {yaml_path}"
                        )
            except Exception as e:
                logger.warning(
                    f"hooks-compact: Failed to load user filters from {yaml_path}: {e}"
                )

    # ── Main pipeline ─────────────────────────────────────────────────────────

    async def on_tool_post(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle tool:post events. Compress bash output when possible.

        Args:
            event: Event name ("tool:post").
            data:  Event data with tool_name, tool_input, result.

        Returns:
            HookResult(action="modify") with compressed output,
            or HookResult(action="continue") to pass through unchanged.
        """
        try:
            return await self._pipeline(data)
        except Exception as e:
            logger.warning(f"hooks-compact: Unexpected error in pipeline: {e}")
            return _CONTINUE

    async def _pipeline(self, data: dict[str, Any]) -> HookResult:
        """Run the 4-stage compression pipeline.

        Raises exceptions freely — caller wraps in try/except (fail-safe).
        """
        # ── Stage 1: CLASSIFY ─────────────────────────────────────────────────
        tool_name = data.get("tool_name", "")
        if tool_name != "bash":
            return _CONTINUE

        tool_input = data.get("tool_input") or {}
        # Amplifier tool:post events carry the tool result under "result", not "tool_result".
        # The "result.output" field is itself a dict: {"returncode": int, "stderr": str, "stdout": str}.
        tool_result = data.get("result") or {}

        command: str = (
            tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        )
        output_obj = (
            tool_result.get("output") if isinstance(tool_result, dict) else None
        )
        output: str | None = (
            output_obj.get("stdout")
            if isinstance(output_obj, dict)
            else output_obj
            if isinstance(output_obj, str)
            else None
        )
        exit_code: int | None = (
            output_obj.get("returncode") if isinstance(output_obj, dict) else None
        )

        if not output or not isinstance(output, str):
            return _CONTINUE

        # Min-lines threshold
        line_count = output.count("\n") + 1
        if line_count < self.min_lines:
            return _CONTINUE

        # Classify command — find matching filter
        match = self._registry.classify(command)
        if match is None:
            return _CONTINUE

        filter_name, filter_fn_or_config = match

        # ── Stage 2: PRE-PROCESS ──────────────────────────────────────────────
        processed = preprocess(output, strip_ansi=self.strip_ansi)

        # ── Stage 3: FILTER ───────────────────────────────────────────────────
        try:
            if callable(filter_fn_or_config):
                # Python filter
                compressed: str = filter_fn_or_config(processed, command, exit_code)
                filter_type = "Python"
            else:
                # YAML filter
                from .filters.yaml_engine import apply_yaml_filter

                compressed = apply_yaml_filter(processed, filter_fn_or_config)
                filter_type = "YAML"
        except Exception as e:
            logger.warning(
                f"hooks-compact: Filter '{filter_name}' raised an exception: {e}"
            )
            return _CONTINUE

        # ── Stage 4: DECIDE ───────────────────────────────────────────────────
        # If filter produced no change or empty result, passthrough
        if not compressed or compressed == output or compressed == processed:
            return _CONTINUE

        # Build stats
        input_chars = len(output)
        output_chars = len(compressed)
        savings_pct = (
            round((1 - output_chars / input_chars) * 100, 1) if input_chars > 0 else 0.0
        )

        # Build modified data — never mutate in-place
        modified_data = copy.deepcopy(data)
        result_obj = modified_data.get("result")
        output_obj_mod = (
            result_obj.get("output") if isinstance(result_obj, dict) else None
        )
        if isinstance(output_obj_mod, dict):
            # Amplifier bash tool: result.output is {"returncode": int, "stderr": str, "stdout": str}
            modified_data["result"]["output"]["stdout"] = compressed
            # Preserve returncode/stderr/success — never modify these
        elif isinstance(output_obj_mod, str):
            # Fallback: output is a plain string
            modified_data["result"]["output"] = compressed
        else:
            # Can't locate where to write the compressed text — passthrough
            return _CONTINUE

        # ── Telemetry ─────────────────────────────────────────────────────────
        if self._telemetry is not None:
            # Strip "cd /path &&" prefix so telemetry shows "git" not "cd"
            clean_command = _strip_shell_prefix(command)
            self._telemetry.log_compression(
                session_id=self._session_id,
                command=clean_command,
                filter_used=filter_name,
                input_chars=input_chars,
                output_chars=output_chars,
                savings_pct=savings_pct,
                exit_code=exit_code,
            )

        # ── User message (debug or savings) ───────────────────────────────────
        user_message: str | None = None

        if self.debug:
            user_message = self._format_debug_message(
                command=command,
                filter_name=filter_name,
                filter_type=filter_type,
                original=output,
                compressed=compressed,
                input_chars=input_chars,
                output_chars=output_chars,
                savings_pct=savings_pct,
            )
        elif self.show_savings:
            user_message = f"bash compressed: {input_chars} → {output_chars} chars ({savings_pct}%)"

        return HookResult(
            action="modify",
            data=modified_data,
            user_message=user_message,
            user_message_level="info",
        )

    @staticmethod
    def _format_debug_message(
        *,
        command: str,
        filter_name: str,
        filter_type: str,
        original: str,
        compressed: str,
        input_chars: int,
        output_chars: int,
        savings_pct: float,
    ) -> str:
        """Format the debug panel shown to the user (not injected into LLM context)."""
        input_lines = original.count("\n") + 1
        output_lines = compressed.count("\n") + 1

        preview_lines = original.split("\n")[:20]
        preview = "\n".join(f"│ {line}" for line in preview_lines)
        if input_lines > 20:
            preview += f"\n│ ... ({input_lines - 20} more lines)"

        compressed_lines_fmt = "\n".join(f"│ {line}" for line in compressed.split("\n"))

        border = "─" * 54
        return (
            f"┌─ hooks-compact debug {border}\n"
            f"│ Command:  {command}\n"
            f"│ Filter:   {filter_name} ({filter_type})\n"
            f"│ Input:    {input_chars} chars ({input_lines} lines)\n"
            f"│ Output:   {output_chars} chars ({output_lines} lines)\n"
            f"│ Savings:  {savings_pct}%\n"
            f"│\n"
            f"│ ── ORIGINAL (first 20 lines) ──\n"
            f"{preview}\n"
            f"│\n"
            f"│ ── COMPRESSED ──\n"
            f"{compressed_lines_fmt}\n"
            f"└{'─' * 76}"
        )
