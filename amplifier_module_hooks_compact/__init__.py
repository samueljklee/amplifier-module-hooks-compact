"""Amplifier hook module that compresses bash tool output before it enters the LLM context.

Intercepts tool:post events for bash tool results and applies command-specific
compression filters to reduce token consumption by 60-90%.

Inspired by RTK (Rust Token Killer): https://github.com/rtk-ai/rtk
"""

from __future__ import annotations

__amplifier_module_type__ = "hook"

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_MODULE_NAME = "hooks-compact"
_VERSION = "0.1.0"


async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> None:
    """Mount the hooks-compact module.

    Registers a tool:post handler that compresses bash tool output
    before it enters the LLM context window.

    Args:
        coordinator: Module coordinator providing hook registry access.
        config: Optional configuration dict. See design doc for full schema.

    Returns:
        None (contract: return None or a cleanup callable — never a dict).
    """
    config = config or {}

    if not config.get("enabled", True):
        logger.info("hooks-compact: Disabled by config")
        return None

    from .hook import CompactHook

    session_id = str(uuid.uuid4())
    hook = CompactHook(config, session_id=session_id)
    coordinator.hooks.register(
        "tool:post",
        hook.on_tool_post,
        priority=50,
        name=_MODULE_NAME,
    )

    logger.info(f"Mounted {_MODULE_NAME} v{_VERSION} (session={session_id[:8]})")
    return None
