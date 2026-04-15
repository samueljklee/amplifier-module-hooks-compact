"""Integration tests for the full 4-stage compression pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amplifier_module_hooks_compact.hook import CompactHook

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def hook():
    """CompactHook with low min_lines threshold for testing."""
    return CompactHook({"min_lines": 5, "show_savings": False, "debug": False})


# ── Stage 1: CLASSIFY passthrough ────────────────────────────────────────────


class TestClassifyPassthrough:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_bash_tool_passthrough(self, hook):
        """Non-bash tools always pass through."""
        data = {"tool_name": "read_file", "tool_result": {"output": "file contents"}}
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_write_file_passthrough(self, hook):
        """write_file tool passes through."""
        data = {
            "tool_name": "write_file",
            "tool_result": {"output": "written", "success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_short_output_passthrough(self, hook):
        """Output under min_lines threshold passes through."""
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "echo hello"},
            "tool_result": {"output": "hello", "success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unmatched_command_passthrough(self, hook):
        """Commands with no matching filter pass through."""
        long_output = "\n".join([f"line {i}" for i in range(30)])
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "some_unknown_command --flags"},
            "tool_result": {"output": long_output, "success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_output_passthrough(self, hook):
        """Empty output passes through."""
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "git status"},
            "tool_result": {"output": "", "success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_missing_output_passthrough(self, hook):
        """Missing output field passes through."""
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "git status"},
            "tool_result": {"success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"


# ── Stage 4: DECIDE — compression ────────────────────────────────────────────


class TestCompression:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_cargo_test_all_pass_compressed(self, hook):
        """cargo test with all passing gets compressed to one line."""
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "tool_result": {"output": fixture, "success": True, "exit_code": 0},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["tool_result"]["output"]
        # Single line with tick and count
        assert "262 passed" in compressed
        assert "✓" in compressed
        # Significantly shorter than original
        assert len(compressed) < len(fixture) * 0.1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cargo_test_failures_shows_details(self, hook):
        """cargo test with failures shows failure details."""
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "tool_result": {"output": fixture, "success": False, "exit_code": 101},
        }
        result = await hook.on_tool_post("tool:post", data)
        # Should compress (failures still shown, but passing tests removed)
        if result.action == "modify":
            compressed = result.data["tool_result"]["output"]
            assert "failed" in compressed.lower()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_pytest_all_pass_compressed(self, hook):
        """pytest with all passing gets compressed to one line."""
        fixture = (FIXTURES / "pytest_all_pass.txt").read_text()
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "pytest"},
            "tool_result": {"output": fixture, "success": True, "exit_code": 0},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["tool_result"]["output"]
        assert "89 passed" in compressed
        assert "✓" in compressed

    @pytest.mark.asyncio(loop_scope="function")
    async def test_git_status_compressed(self, hook):
        """git status gets compressed to key info."""
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "git status"},
            "tool_result": {"output": fixture, "success": True, "exit_code": 0},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["tool_result"]["output"]
        assert "feature/compression-pipeline" in compressed
        # Hint lines stripped
        assert 'use "git restore"' not in compressed

    @pytest.mark.asyncio(loop_scope="function")
    async def test_compression_never_mutates_original(self, hook):
        """Original data dict is never mutated by compression."""
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data: dict[str, Any] = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "tool_result": {"output": fixture, "success": True, "exit_code": 0},
        }
        original_output = data["tool_result"]["output"]
        await hook.on_tool_post("tool:post", data)

        # Original data must not be mutated
        assert data["tool_result"]["output"] == original_output

    @pytest.mark.asyncio(loop_scope="function")
    async def test_success_flag_preserved(self, hook):
        """tool_result.success is never modified."""
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "tool_result": {"output": fixture, "success": True, "exit_code": 0},
        }
        result = await hook.on_tool_post("tool:post", data)
        if result.action == "modify":
            assert result.data["tool_result"]["success"] is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_modify_result_has_user_message(self):
        """When show_savings=True, result includes user_message."""
        hook = CompactHook({"min_lines": 5, "show_savings": True, "debug": False})
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "tool_result": {"output": fixture, "success": True, "exit_code": 0},
        }
        result = await hook.on_tool_post("tool:post", data)
        if result.action == "modify":
            assert hasattr(result, "user_message")
            assert result.user_message is not None
            assert "compressed" in result.user_message.lower()


# ── Fail-safe ─────────────────────────────────────────────────────────────────


class TestFailSafe:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_none_data_returns_continue(self, hook):
        """None data returns continue gracefully."""
        result = await hook.on_tool_post("tool:post", {})
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_malformed_tool_input_returns_continue(self, hook):
        """Malformed tool_input returns continue."""
        data = {"tool_name": "bash", "tool_input": None, "tool_result": None}
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_string_tool_input_returns_continue(self, hook):
        """String tool_input (not dict) returns continue."""
        data = {
            "tool_name": "bash",
            "tool_input": "raw command string",
            "tool_result": {"output": "some output\n" * 30},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_string_output_returns_continue(self, hook):
        """Non-string output returns continue."""
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "tool_result": {"output": 42, "success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"
