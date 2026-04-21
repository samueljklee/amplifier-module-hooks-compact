"""Amplifier hook module that compresses bash tool output before it enters the LLM context.

Intercepts tool:post events for bash tool results and applies command-specific
compression filters to reduce token consumption by 60-90%.

Inspired by RTK (Rust Token Killer): https://github.com/rtk-ai/rtk
"""

from __future__ import annotations

__amplifier_module_type__ = "hook"

import logging
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Any

logger = logging.getLogger(__name__)

_MODULE_NAME = "hooks-compact"

try:
    _VERSION = _pkg_version("amplifier-module-hooks-compact")
except PackageNotFoundError:
    _VERSION = "unknown"


async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> Any:
    """Mount the hooks-compact module.

    Registers a tool:post handler that compresses bash tool output
    before it enters the LLM context window.

    Args:
        coordinator: Module coordinator providing hook registry access.
        config: Optional configuration dict. See design doc for full schema.

    Returns:
        Unregister callable from hooks.register(), or None if disabled.
    """
    config = config or {}

    if not config.get("enabled", True):
        logger.info("hooks-compact: Disabled by config")
        return None

    from .hook import CompactHook
    from .telemetry import compute_config_hash

    session_id = coordinator.session_id
    hook = CompactHook(config, session_id=session_id)

    # Compute config fingerprint once for the session
    yaml_bytes = ""
    try:
        from pathlib import Path

        for candidate in [
            Path.cwd() / ".amplifier" / "output-filters.yaml",
            Path.home() / ".amplifier" / "output-filters.yaml",
        ]:
            if candidate.exists():
                yaml_bytes = candidate.read_text()
                break
    except Exception:
        yaml_bytes = ""

    hook._config_hash = compute_config_hash(
        config=config,
        yaml_bytes=yaml_bytes,
        version=_VERSION,
    )

    unregister = coordinator.hooks.register(
        "tool:post",
        hook.on_tool_post,
        priority=50,
        name=_MODULE_NAME,
    )

    logger.info(f"Mounted {_MODULE_NAME} v{_VERSION} (session={session_id[:8]})")
    return unregister
