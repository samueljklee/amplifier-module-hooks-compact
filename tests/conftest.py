"""Shared pytest configuration and fixtures for hooks-compact tests."""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Path helpers ──────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a fixture file by name (relative to tests/fixtures/)."""
    return (FIXTURES_DIR / name).read_text()


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def minimal_hook():
    """Create a CompactHook with minimal config (low min_lines for testing)."""
    from amplifier_module_hooks_compact.hook import CompactHook

    return CompactHook({"min_lines": 5, "show_savings": False, "debug": False})
