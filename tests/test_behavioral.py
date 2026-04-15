"""Behavioral tests for the hook module.

Inherits HookBehaviorTests from amplifier_core if available.
These validate that the hook behaves correctly within the Amplifier event system.
"""

from __future__ import annotations

import pytest

try:
    from amplifier_core.validation.behavioral import HookBehaviorTests  # type: ignore[import-untyped]

    class TestCompactHookBehavior(HookBehaviorTests):  # pyright: ignore[reportRedeclaration]
        """Inherits kernel behavioral validation tests."""

        pass

except ImportError:
    pytest.skip("amplifier-core not installed", allow_module_level=True)
