"""Tests for __init__.py module-level attributes."""

from __future__ import annotations

from typing import Callable

import pytest


class TestVersionSSoT:
    def test_version_reads_from_package_metadata(self) -> None:
        """_VERSION should come from importlib.metadata, not a hardcoded string."""
        from amplifier_module_hooks_compact import _VERSION

        # When the package is installed (editable or not), _VERSION must match
        # pyproject.toml's version field — currently "0.1.0".
        assert _VERSION == "0.1.0"
        assert _VERSION != "unknown"

    def test_version_is_not_hardcoded(self) -> None:
        """Ensure we're actually reading from metadata, not a string literal."""
        import importlib.metadata

        expected = importlib.metadata.version("amplifier-module-hooks-compact")
        from amplifier_module_hooks_compact import _VERSION

        assert _VERSION == expected


class _FakeHookRegistry:
    """Minimal stub for coordinator.hooks that records register() calls."""

    def __init__(self) -> None:
        self.registered: list[tuple] = []

    def register(self, event: str, handler, **kwargs) -> Callable[[], None]:
        self.registered.append((event, handler, kwargs))

        # Return a callable "unregister" function, like the real coordinator does
        def unregister() -> None:
            pass

        return unregister


class _FakeCoordinator:
    """Minimal stub for the coordinator passed to mount()."""

    def __init__(self, session_id: str = "coord-session-abc123") -> None:
        self.session_id = session_id
        self.hooks = _FakeHookRegistry()


class TestMountSessionId:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_mount_uses_coordinator_session_id(self) -> None:
        """mount() must use coordinator.session_id, NOT uuid.uuid4()."""
        from amplifier_module_hooks_compact import mount

        coordinator = _FakeCoordinator(session_id="coord-session-xyz789")
        await mount(coordinator, config={"telemetry": {"local": False}})

        # The hook handler was registered — grab the handler instance
        assert len(coordinator.hooks.registered) == 1
        _event, handler, _kwargs = coordinator.hooks.registered[0]

        # handler is a bound method on a CompactHook instance
        hook_instance = handler.__self__
        assert hook_instance._session_id == "coord-session-xyz789"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mount_does_not_use_uuid(self) -> None:
        """Verify uuid is no longer imported or used in __init__.py."""
        import amplifier_module_hooks_compact as mod
        import inspect

        source = inspect.getsource(mod)
        assert "uuid.uuid4" not in source
        assert "import uuid" not in source


class TestMountUnregister:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_mount_returns_unregister_callable(self) -> None:
        """mount() must return the unregister callable from hooks.register()."""
        from amplifier_module_hooks_compact import mount

        coordinator = _FakeCoordinator()
        result = await mount(coordinator, config={"telemetry": {"local": False}})

        # result must be a callable (the unregister function), not None
        assert result is not None
        assert callable(result)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mount_disabled_returns_none(self) -> None:
        """mount() with enabled=False should return None (no hook registered)."""
        from amplifier_module_hooks_compact import mount

        coordinator = _FakeCoordinator()
        result = await mount(coordinator, config={"enabled": False})

        assert result is None
