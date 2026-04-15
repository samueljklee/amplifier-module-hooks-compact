"""Tests for the SQLite-backed local telemetry store."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from amplifier_module_hooks_compact.telemetry import TelemetryStore


# ── log_compression() ───────────────────────────────────────────────────────


class TestLogCompression:
    def test_writes_row_to_database(self, tmp_path: Path) -> None:
        """log_compression() inserts a row with all expected fields."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        store.log_compression(
            session_id="test-session",
            command="cargo test",
            filter_used="cargo-test",
            input_chars=1000,
            output_chars=200,
            savings_pct=80.0,
            exit_code=0,
        )
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM compression_log").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["session_id"] == "test-session"
        assert row["command"] == "cargo"  # only the first token is stored
        assert row["filter_used"] == "cargo-test"
        assert row["input_chars"] == 1000
        assert row["output_chars"] == 200
        assert row["savings_pct"] == 80.0
        assert row["exit_code"] == 0

    def test_only_first_command_token_stored(self, tmp_path: Path) -> None:
        """log_compression() strips command arguments — only the first word is stored."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        store.log_compression(
            session_id="s",
            command="git status --short",
            filter_used="git-status",
            input_chars=100,
            output_chars=10,
            savings_pct=90.0,
            exit_code=0,
        )
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT command FROM compression_log").fetchone()
        assert row[0] == "git"  # arguments not stored

    def test_multiple_writes_accumulate(self, tmp_path: Path) -> None:
        """Multiple log_compression calls append rows rather than overwriting."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        for _ in range(5):
            store.log_compression(
                session_id="s1",
                command="git status",
                filter_used="git-status",
                input_chars=100,
                output_chars=10,
                savings_pct=90.0,
                exit_code=0,
            )
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compression_log").fetchone()[0]
        assert count == 5

    def test_disabled_store_does_not_write(self, tmp_path: Path) -> None:
        """When local=False, log_compression() is a no-op and no db is created."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": False})
        store.log_compression(
            session_id="s1",
            command="cargo test",
            filter_used="cargo-test",
            input_chars=100,
            output_chars=10,
            savings_pct=90.0,
            exit_code=0,
        )
        assert not db.exists()

    def test_null_exit_code_stored(self, tmp_path: Path) -> None:
        """exit_code=None is stored correctly (NULL in SQLite)."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        store.log_compression(
            session_id="s",
            command="make",
            filter_used="make",
            input_chars=50,
            output_chars=5,
            savings_pct=90.0,
            exit_code=None,
        )
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT exit_code FROM compression_log").fetchone()
        assert row[0] is None


# ── get_session_summary() ───────────────────────────────────────────────────


class TestGetSessionSummary:
    def test_returns_correct_aggregates(self, tmp_path: Path) -> None:
        """get_session_summary() returns total_commands, sums, and avg_savings."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        store.log_compression(
            session_id="sess",
            command="git status",
            filter_used="git-status",
            input_chars=200,
            output_chars=50,
            savings_pct=75.0,
            exit_code=0,
        )
        store.log_compression(
            session_id="sess",
            command="git diff",
            filter_used="git-diff",
            input_chars=400,
            output_chars=100,
            savings_pct=75.0,
            exit_code=0,
        )
        summary = store.get_session_summary("sess")
        assert summary["total_commands"] == 2
        assert summary["total_input_chars"] == 600
        assert summary["total_output_chars"] == 150
        assert summary["avg_savings_pct"] == 75.0

    def test_breakdown_by_command(self, tmp_path: Path) -> None:
        """get_session_summary() includes a per-command breakdown dict."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        for _ in range(3):
            store.log_compression(
                session_id="sess",
                command="cargo test",
                filter_used="cargo-test",
                input_chars=100,
                output_chars=10,
                savings_pct=90.0,
                exit_code=0,
            )
        store.log_compression(
            session_id="sess",
            command="git status",
            filter_used="git-status",
            input_chars=100,
            output_chars=50,
            savings_pct=50.0,
            exit_code=0,
        )
        summary = store.get_session_summary("sess")
        breakdown = summary["breakdown_by_command"]
        assert "cargo" in breakdown
        assert breakdown["cargo"]["count"] == 3
        assert "git" in breakdown
        assert breakdown["git"]["count"] == 1

    def test_empty_summary_for_unknown_session(self, tmp_path: Path) -> None:
        """get_session_summary() returns {} for a session with no records."""
        db = tmp_path / "telemetry.db"
        TelemetryStore({"db_path": str(db), "local": True})
        store = TelemetryStore({"db_path": str(db), "local": True})
        summary = store.get_session_summary("nonexistent")
        assert summary == {}

    def test_isolates_by_session_id(self, tmp_path: Path) -> None:
        """get_session_summary() only aggregates rows for the requested session."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        store.log_compression(
            session_id="sess-A",
            command="git status",
            filter_used="git-status",
            input_chars=100,
            output_chars=10,
            savings_pct=90.0,
            exit_code=0,
        )
        store.log_compression(
            session_id="sess-B",
            command="git status",
            filter_used="git-status",
            input_chars=100,
            output_chars=10,
            savings_pct=90.0,
            exit_code=0,
        )
        summary_a = store.get_session_summary("sess-A")
        assert summary_a["total_commands"] == 1


# ── Auto-create directory and table ─────────────────────────────────────────


class TestAutoCreate:
    def test_creates_nested_directory_on_init(self, tmp_path: Path) -> None:
        """TelemetryStore creates the parent directory tree automatically."""
        db = tmp_path / "a" / "b" / "c" / "telemetry.db"
        assert not db.parent.exists()
        TelemetryStore({"db_path": str(db), "local": True})
        assert db.parent.exists()
        assert db.exists()

    def test_creates_compression_log_table(self, tmp_path: Path) -> None:
        """TelemetryStore creates the compression_log table on first init."""
        db = tmp_path / "telemetry.db"
        TelemetryStore({"db_path": str(db), "local": True})
        with sqlite3.connect(db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        assert "compression_log" in [t[0] for t in tables]

    def test_idempotent_init(self, tmp_path: Path) -> None:
        """Initialising TelemetryStore twice does not raise or corrupt data."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore({"db_path": str(db), "local": True})
        store.log_compression(
            session_id="s",
            command="make",
            filter_used="make",
            input_chars=10,
            output_chars=1,
            savings_pct=90.0,
            exit_code=0,
        )
        # Second init
        TelemetryStore({"db_path": str(db), "local": True})
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compression_log").fetchone()[0]
        assert count == 1  # existing row not deleted


# ── retention_days pruning ───────────────────────────────────────────────────


class TestRetentionDays:
    def test_prunes_records_older_than_retention(self, tmp_path: Path) -> None:
        """Records beyond retention_days are deleted on TelemetryStore init."""
        db = tmp_path / "telemetry.db"
        # Pre-populate DB with a record that is 120 days old
        db.parent.mkdir(parents=True, exist_ok=True)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        with sqlite3.connect(db) as conn:
            conn.execute(
                """
                CREATE TABLE compression_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT NOT NULL,
                    session_id   TEXT NOT NULL,
                    command      TEXT NOT NULL,
                    filter_used  TEXT,
                    input_chars  INTEGER NOT NULL,
                    output_chars INTEGER NOT NULL,
                    savings_pct  REAL NOT NULL,
                    exit_code    INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO compression_log "
                "VALUES (NULL, ?, 's', 'cmd', NULL, 1, 1, 0.0, 0)",
                (old_ts,),
            )
            conn.commit()
        # Init with 90-day retention → 120-day record should be pruned
        TelemetryStore({"db_path": str(db), "local": True, "retention_days": 90})
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compression_log").fetchone()[0]
        assert count == 0

    def test_keeps_recent_records(self, tmp_path: Path) -> None:
        """Records within retention_days survive a re-init."""
        db = tmp_path / "telemetry.db"
        store = TelemetryStore(
            {"db_path": str(db), "local": True, "retention_days": 90}
        )
        store.log_compression(
            session_id="s",
            command="git status",
            filter_used="git-status",
            input_chars=100,
            output_chars=10,
            savings_pct=90.0,
            exit_code=0,
        )
        # Re-init with same config — recent record should survive
        TelemetryStore({"db_path": str(db), "local": True, "retention_days": 90})
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compression_log").fetchone()[0]
        assert count == 1
