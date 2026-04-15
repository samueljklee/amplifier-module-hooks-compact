"""Structural validation tests.

Inherits HookStructuralTests from amplifier_core if available.
These validate that the module conforms to the hook module protocol.
"""

from __future__ import annotations

import pytest

try:
    from amplifier_core.validation.structural import HookStructuralTests  # type: ignore[import-untyped]

    class TestCompactHookStructural(HookStructuralTests):  # pyright: ignore[reportRedeclaration]
        """Inherits kernel structural validation tests."""

        pass

except ImportError:
    pytest.skip("amplifier-core not installed", allow_module_level=True)
