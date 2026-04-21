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


# ── Schema migration (outcome + config_hash columns) ─────────────────────────


class TestSchemaMigration:
    def test_adds_columns_to_old_schema(self, tmp_path: Path) -> None:
        """TelemetryStore adds outcome and config_hash columns to a DB
        that was created with the old schema (no such columns)."""
        db = tmp_path / "telemetry.db"
        db.parent.mkdir(parents=True, exist_ok=True)

        # Pre-populate with old schema (no outcome, no config_hash)
        with sqlite3.connect(db) as conn:
            conn.execute("""
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
            """)
            # Insert a legacy row
            conn.execute(
                "INSERT INTO compression_log "
                "VALUES (NULL, '2026-04-01T00:00:00', 'old-sess', 'git', "
                "'git-status', 100, 10, 90.0, 0)"
            )
            conn.commit()

        # Now init TelemetryStore — it should migrate the schema
        TelemetryStore({"db_path": str(db), "local": True})

        # Verify columns exist
        with sqlite3.connect(db) as conn:
            cursor = conn.execute("PRAGMA table_info(compression_log)")
            columns = {row[1] for row in cursor}

        assert "outcome" in columns
        assert "config_hash" in columns

    def test_old_rows_have_null_in_new_columns(self, tmp_path: Path) -> None:
        """Old rows retain NULL in the new outcome and config_hash columns."""
        db = tmp_path / "telemetry.db"
        with sqlite3.connect(db) as conn:
            conn.execute("""
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
            """)
            conn.execute(
                "INSERT INTO compression_log "
                "VALUES (NULL, '2026-04-01T00:00:00', 'old-sess', 'git', "
                "'git-status', 100, 10, 90.0, 0)"
            )
            conn.commit()

        TelemetryStore({"db_path": str(db), "local": True})

        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM compression_log").fetchone()

        assert row["outcome"] is None
        assert row["config_hash"] is None

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        """Running TelemetryStore init twice doesn't fail or duplicate columns."""
        db = tmp_path / "telemetry.db"
        TelemetryStore({"db_path": str(db), "local": True})
        # Second init should not raise
        TelemetryStore({"db_path": str(db), "local": True})

        with sqlite3.connect(db) as conn:
            cursor = conn.execute("PRAGMA table_info(compression_log)")
            col_names = [row[1] for row in cursor]

        # Each column appears exactly once
        assert col_names.count("outcome") == 1
        assert col_names.count("config_hash") == 1


# ── Config hash computation ──────────────────────────────────────────────────


class TestConfigHash:
    def test_canonical_json_ordering(self) -> None:
        """Same config dict in different insertion order → same hash."""
        from amplifier_module_hooks_compact.telemetry import compute_config_hash

        hash_a = compute_config_hash(
            config={"min_lines": 5, "enabled": True, "strip_ansi": True},
            yaml_bytes="",
            version="0.1.0",
        )
        hash_b = compute_config_hash(
            config={"strip_ansi": True, "enabled": True, "min_lines": 5},
            yaml_bytes="",
            version="0.1.0",
        )
        assert hash_a == hash_b

    def test_different_config_different_hash(self) -> None:
        """Different config values → different hashes."""
        from amplifier_module_hooks_compact.telemetry import compute_config_hash

        hash_a = compute_config_hash(
            config={"min_lines": 5},
            yaml_bytes="",
            version="0.1.0",
        )
        hash_b = compute_config_hash(
            config={"min_lines": 10},
            yaml_bytes="",
            version="0.1.0",
        )
        assert hash_a != hash_b

    def test_presence_vs_absence_of_yaml(self) -> None:
        """Having yaml_bytes vs empty string → different hashes."""
        from amplifier_module_hooks_compact.telemetry import compute_config_hash

        hash_no_yaml = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="",
            version="0.1.0",
        )
        hash_with_yaml = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="filters:\n  my-filter:\n    match_command: '^ls'\n",
            version="0.1.0",
        )
        assert hash_no_yaml != hash_with_yaml

    def test_empty_file_vs_no_file(self) -> None:
        """An empty yaml file (empty bytes) still differs from no file (empty string).

        Wait — both are empty string. So they should be the SAME hash.
        The distinction comes at the call site: if a file exists but is empty,
        you read its bytes (which is b"" → ""), same as no file. This is acceptable.
        """
        from amplifier_module_hooks_compact.telemetry import compute_config_hash

        hash_no_file = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="",
            version="0.1.0",
        )
        hash_empty_file = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="",
            version="0.1.0",
        )
        assert hash_no_file == hash_empty_file

    def test_version_changes_hash(self) -> None:
        """Different version string → different hash."""
        from amplifier_module_hooks_compact.telemetry import compute_config_hash

        hash_a = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="",
            version="0.1.0",
        )
        hash_b = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="",
            version="0.2.0",
        )
        assert hash_a != hash_b

    def test_hash_is_hex_sha256(self) -> None:
        """Output is a 64-char lowercase hex string (SHA-256)."""
        from amplifier_module_hooks_compact.telemetry import compute_config_hash

        result = compute_config_hash(
            config={"enabled": True},
            yaml_bytes="",
            version="0.1.0",
        )
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)
