"""Tests for mount() lifecycle — config parsing, handler registration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from amplifier_module_hooks_compact import mount


def _make_coordinator():
    """Create a mock coordinator with hooks.register()."""
    coordinator = MagicMock()
    coordinator.hooks = MagicMock()
    coordinator.hooks.register = MagicMock(
        return_value=MagicMock()
    )  # returns unregister fn
    return coordinator


class TestMountRegistration:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_registers_tool_post_hook(self):
        """mount() registers a handler on tool:post."""
        coordinator = _make_coordinator()
        await mount(coordinator, config=None)

        coordinator.hooks.register.assert_called_once()
        call_args = coordinator.hooks.register.call_args
        assert call_args[0][0] == "tool:post"  # first positional arg is event name

    @pytest.mark.asyncio(loop_scope="function")
    async def test_registers_with_priority_50(self):
        """Hook registers at priority 50 (after redaction at 10, before logging at 90)."""
        coordinator = _make_coordinator()
        await mount(coordinator, config=None)

        call_kwargs = coordinator.hooks.register.call_args[1]
        assert call_kwargs.get("priority") == 50

    @pytest.mark.asyncio(loop_scope="function")
    async def test_registers_with_correct_name(self):
        """Hook registers with name 'hooks-compact'."""
        coordinator = _make_coordinator()
        await mount(coordinator, config=None)

        call_kwargs = coordinator.hooks.register.call_args[1]
        assert call_kwargs.get("name") == "hooks-compact"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_none_when_disabled(self):
        """When config has enabled=False, mount() returns None without registering."""
        coordinator = _make_coordinator()
        result = await mount(coordinator, config={"enabled": False})

        assert result is None
        coordinator.hooks.register.assert_not_called()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_config_defaults(self):
        """Default config values are applied when config is None."""
        coordinator = _make_coordinator()
        await mount(coordinator, config=None)

        # Hook was registered (defaults applied successfully)
        coordinator.hooks.register.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_none_or_cleanup_callable(self):
        """mount() must return None or a cleanup callable — never a dict."""
        coordinator = _make_coordinator()
        result = await mount(coordinator, config=None)

        assert result is None or callable(result), (
            f"mount() must return None or a cleanup callable, got {type(result)!r}"
        )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_handler_is_callable(self):
        """The registered handler must be callable."""
        coordinator = _make_coordinator()
        await mount(coordinator, config=None)

        call_args = coordinator.hooks.register.call_args
        handler = call_args[0][1]  # second positional arg is the handler
        assert callable(handler)
