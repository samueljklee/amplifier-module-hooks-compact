"""Integration tests for the full 4-stage compression pipeline."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import pytest

from amplifier_module_hooks_compact.hook import CompactHook

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def hook():
    """CompactHook with low min_lines threshold for testing."""
    return CompactHook({"min_lines": 5, "show_savings": False, "debug": False})


def make_bash_event(
    command: str,
    stdout: str,
    returncode: int = 0,
    success: bool = True,
) -> dict[str, Any]:
    """Build an Amplifier tool:post event for bash with the real event shape.

    The actual Amplifier kernel emits tool:post with:
      data["result"]["output"]["stdout"] = <stdout string>
      data["result"]["output"]["returncode"] = <int>
    """
    return {
        "tool_name": "bash",
        "tool_input": {"command": command},
        "result": {
            "output": {"returncode": returncode, "stderr": "", "stdout": stdout},
            "success": success,
            "error": None,
        },
    }


# ── Stage 1: CLASSIFY passthrough ────────────────────────────────────────────


class TestClassifyPassthrough:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_bash_tool_passthrough(self, hook):
        """Non-bash tools always pass through."""
        data = {
            "tool_name": "read_file",
            "result": {
                "output": {"returncode": 0, "stdout": "file contents"},
                "success": True,
            },
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_write_file_passthrough(self, hook):
        """write_file tool passes through."""
        data = {
            "tool_name": "write_file",
            "result": {
                "output": {"returncode": 0, "stdout": "written"},
                "success": True,
            },
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_short_output_passthrough(self, hook):
        """Output under min_lines threshold passes through."""
        data = make_bash_event("echo hello", "hello")
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unmatched_command_passthrough(self, hook):
        """Commands with no matching filter pass through."""
        long_output = "\n".join([f"line {i}" for i in range(30)])
        data = make_bash_event("some_unknown_command --flags", long_output)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_output_passthrough(self, hook):
        """Empty output passes through."""
        data = make_bash_event("git status", "")
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_missing_output_passthrough(self, hook):
        """Missing stdout field passes through."""
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "git status"},
            "result": {"output": {"returncode": 0, "stderr": ""}, "success": True},
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"


# ── Stage 4: DECIDE — compression ────────────────────────────────────────────


class TestCompression:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_cargo_test_all_pass_compressed(self, hook):
        """cargo test with all passing gets compressed to one line."""
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = make_bash_event("cargo test", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["result"]["output"]["stdout"]
        # Single line with tick and count
        assert "262 passed" in compressed
        assert "✓" in compressed
        # Significantly shorter than original
        assert len(compressed) < len(fixture) * 0.1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cargo_test_failures_shows_details(self, hook):
        """cargo test with failures shows failure details."""
        fixture = (FIXTURES / "cargo_test_failures.txt").read_text()
        data = make_bash_event("cargo test", fixture, returncode=101, success=False)
        result = await hook.on_tool_post("tool:post", data)
        # Should compress (failures still shown, but passing tests removed)
        if result.action == "modify":
            compressed = result.data["result"]["output"]["stdout"]
            assert "failed" in compressed.lower()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_pytest_all_pass_compressed(self, hook):
        """pytest with all passing gets compressed to one line."""
        fixture = (FIXTURES / "pytest_all_pass.txt").read_text()
        data = make_bash_event("pytest", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["result"]["output"]["stdout"]
        assert "89 passed" in compressed
        assert "✓" in compressed

    @pytest.mark.asyncio(loop_scope="function")
    async def test_git_status_compressed(self, hook):
        """git status gets compressed to key info."""
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        data = make_bash_event("git status", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["result"]["output"]["stdout"]
        assert "feature/compression-pipeline" in compressed
        # Hint lines stripped
        assert 'use "git restore"' not in compressed

    @pytest.mark.asyncio(loop_scope="function")
    async def test_git_diff_compressed_shows_what_changed(self, hook):
        """git diff compressed output shows what actually changed (not just file count)."""
        fixture = (FIXTURES / "git_diff_unified.txt").read_text()
        data = make_bash_event("git diff", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"
        compressed = result.data["result"]["output"]["stdout"]
        # Should include file names
        assert "src/auth.py" in compressed or "auth.py" in compressed
        # Should include actual change content (+ or - lines)
        assert "+" in compressed or "-" in compressed
        # Should still be shorter than original
        assert len(compressed) < len(fixture)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_compression_never_mutates_original(self, hook):
        """Original data dict is never mutated by compression."""
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = make_bash_event("cargo test", fixture, returncode=0, success=True)
        original_stdout = data["result"]["output"]["stdout"]
        await hook.on_tool_post("tool:post", data)

        # Original data must not be mutated
        assert data["result"]["output"]["stdout"] == original_stdout

    @pytest.mark.asyncio(loop_scope="function")
    async def test_success_flag_preserved(self, hook):
        """result.success is never modified."""
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = make_bash_event("cargo test", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        if result.action == "modify":
            assert result.data["result"]["success"] is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_modify_result_has_user_message(self):
        """When show_savings=True, result includes user_message."""
        hook = CompactHook({"min_lines": 5, "show_savings": True, "debug": False})
        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = make_bash_event("cargo test", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        if result.action == "modify":
            assert hasattr(result, "user_message")
            assert result.user_message is not None
            assert "compressed" in result.user_message.lower()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cd_prefix_command_still_compressed(self, hook):
        """Commands prefixed with 'cd /path &&' are still classified and compressed."""
        fixture = (FIXTURES / "git_status_dirty.txt").read_text()
        data = make_bash_event(
            "cd /Users/samule/repo/my-project && git status",
            fixture,
            returncode=0,
            success=True,
        )
        result = await hook.on_tool_post("tool:post", data)
        # Should compress even with cd prefix
        assert result.action == "modify"


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
        data = {"tool_name": "bash", "tool_input": None, "result": None}
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_string_tool_input_returns_continue(self, hook):
        """String tool_input (not dict) returns continue."""
        long_output = "some output\n" * 30
        data = {
            "tool_name": "bash",
            "tool_input": "raw command string",
            "result": {
                "output": {"returncode": 0, "stdout": long_output},
                "success": True,
            },
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_string_output_returns_continue(self, hook):
        """Non-string stdout field returns continue."""
        data = {
            "tool_name": "bash",
            "tool_input": {"command": "cargo test"},
            "result": {
                "output": {"returncode": 0, "stdout": 42},
                "success": True,
            },
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"


# ── Filter exception passthrough (R9) ────────────────────────────────────────


class TestFilterExceptionPassthrough:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_filter_exception_triggers_passthrough(self, tmp_path):
        """A filter that raises RuntimeError must not crash the hook.

        The hook should return action='continue' (passthrough) and log
        a telemetry row with outcome='filter_error'.
        """
        db = tmp_path / "telemetry.db"
        hook = CompactHook(
            {
                "min_lines": 5,
                "show_savings": False,
                "debug": False,
                "telemetry": {"local": True, "db_path": str(db)},
            },
            session_id="err-session",
        )

        # Monkey-patch: register a filter that always raises
        def _exploding_filter(output, command, exit_code):
            raise RuntimeError("boom")

        hook._registry._python_filters.insert(
            0,
            (
                "exploding",
                __import__("re").compile(r"^git\s+status\b"),
                _exploding_filter,
            ),
        )

        long_output = "\n".join([f"line {i}" for i in range(30)])
        data = make_bash_event("git status", long_output)
        result = await hook.on_tool_post("tool:post", data)

        # Fail-safe: hook returns continue, user sees original output unchanged
        assert result.action == "continue"

        # Telemetry: a row with outcome='filter_error' was logged
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM compression_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome"] == "filter_error"


# ── Outcome logging ───────────────────────────────────────────────────────────


class TestOutcomeLogging:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_compressed_outcome(self, tmp_path):
        """A successful compression logs outcome='compressed'."""
        db = tmp_path / "telemetry.db"
        hook = CompactHook(
            {
                "min_lines": 5,
                "show_savings": False,
                "debug": False,
                "telemetry": {"local": True, "db_path": str(db)},
            },
            session_id="compressed-session",
        )

        fixture = (FIXTURES / "cargo_test_all_pass.txt").read_text()
        data = make_bash_event("cargo test", fixture, returncode=0, success=True)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "modify"

        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM compression_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome"] == "compressed"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_no_match_outcome(self, tmp_path):
        """A bash command with no matching filter logs outcome='no_match'."""
        db = tmp_path / "telemetry.db"
        hook = CompactHook(
            {
                "min_lines": 5,
                "show_savings": False,
                "debug": False,
                "telemetry": {"local": True, "db_path": str(db)},
            },
            session_id="nomatch-session",
        )

        long_output = "\n".join([f"line {i}" for i in range(30)])
        data = make_bash_event("some_unknown_command --flags", long_output)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM compression_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome"] == "no_match"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_passthrough_outcome(self, tmp_path):
        """A filter that returns the same output logs outcome='passthrough'."""
        db = tmp_path / "telemetry.db"
        hook = CompactHook(
            {
                "min_lines": 5,
                "show_savings": False,
                "debug": False,
                "telemetry": {"local": True, "db_path": str(db)},
            },
            session_id="passthrough-session",
        )

        # Register an identity filter that returns input unchanged
        def _identity_filter(output, command, exit_code):
            return output

        hook._registry._python_filters.insert(
            0, ("identity", __import__("re").compile(r"^echo\b"), _identity_filter)
        )

        long_output = "\n".join([f"line {i}" for i in range(30)])
        data = make_bash_event("echo hello", long_output)
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM compression_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome"] == "passthrough"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_bash_tool_logs_nothing(self, tmp_path):
        """Non-bash tools must not create any telemetry row."""
        db = tmp_path / "telemetry.db"
        hook = CompactHook(
            {
                "min_lines": 5,
                "show_savings": False,
                "debug": False,
                "telemetry": {"local": True, "db_path": str(db)},
            },
            session_id="nonbash-session",
        )

        data = {
            "tool_name": "read_file",
            "result": {
                "output": {"returncode": 0, "stdout": "file contents\n" * 30},
                "success": True,
            },
        }
        result = await hook.on_tool_post("tool:post", data)
        assert result.action == "continue"

        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compression_log").fetchone()[0]
        assert count == 0
