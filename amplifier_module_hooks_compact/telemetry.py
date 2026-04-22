"""SQLite-backed local telemetry for compression statistics.

Stores compression events in a local SQLite database.
All data stays on the user's machine — no remote transmission.
Users can disable via config: telemetry.local = false
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "~/.amplifier/hooks-compact/telemetry.db"
_DEFAULT_RETENTION_DAYS = 90


def compute_config_hash(
    *,
    config: dict[str, Any],
    yaml_bytes: str,
    version: str,
) -> str:
    """Compute a SHA-256 fingerprint of the hook's effective configuration.

    The hash captures three components separated by ``\\n---\\n``:
    1. Canonical JSON of the merged config dict (sorted keys, compact).
    2. Raw bytes of any loaded user/project output-filters.yaml (or "" if absent).
    3. Current _VERSION string.

    Computed once at mount time. Same hash for all rows in a session.
    Restart to pick up filter changes.

    Args:
        config: The effective merged configuration dict.
        yaml_bytes: Raw file contents of output-filters.yaml, or "" if no file.
        version: The _VERSION string from __init__.py.

    Returns:
        64-char lowercase hex SHA-256 digest.
    """
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
    payload = f"{config_json}\n---\n{yaml_bytes}\n---\n{version}"
    return hashlib.sha256(payload.encode()).hexdigest()


class TelemetryStore:
    """Local SQLite telemetry store for compression statistics.

    Creates the database and schema on first use.
    Auto-prunes records older than retention_days on startup.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.enabled = cfg.get("local", True)
        self._retention_days: int = int(
            cfg.get("retention_days", _DEFAULT_RETENTION_DAYS)
        )

        raw_path = cfg.get("db_path", _DEFAULT_DB_PATH)
        self._db_path = Path(raw_path).expanduser()

        if self.enabled:
            try:
                self._init_db()
            except Exception as e:
                logger.warning(f"hooks-compact telemetry: Failed to initialize DB: {e}")
                self.enabled = False

    def _init_db(self) -> None:
        """Create directory, table, and prune old records."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS compression_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT NOT NULL,
                    session_id   TEXT NOT NULL,
                    command      TEXT NOT NULL,
                    filter_used  TEXT,
                    input_chars  INTEGER NOT NULL,
                    output_chars INTEGER NOT NULL,
                    savings_pct  REAL NOT NULL,
                    exit_code    INTEGER,
                    outcome      TEXT,
                    config_hash  TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session ON compression_log (session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON compression_log (timestamp)"
            )

            # ── Schema migration: add columns to pre-existing old-schema DBs ──
            # Idempotent: skips columns that already exist.
            try:
                cursor = conn.execute("PRAGMA table_info(compression_log)")
                existing = {row[1] for row in cursor}
                for col, typ in [("outcome", "TEXT"), ("config_hash", "TEXT")]:
                    if col not in existing:
                        conn.execute(
                            f"ALTER TABLE compression_log ADD COLUMN {col} {typ}"
                        )
            except Exception as e:
                logger.warning(f"hooks-compact telemetry: Schema migration failed: {e}")

            conn.commit()

        self._prune_old_records()

    def _prune_old_records(self) -> None:
        """Delete records older than retention_days."""
        if not self._db_path.exists():
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "DELETE FROM compression_log WHERE timestamp < ?",
                    (cutoff.isoformat(),),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"hooks-compact telemetry: Failed to prune old records: {e}")

    def log_compression(
        self,
        *,
        session_id: str,
        command: str,
        filter_used: str | None,
        input_chars: int,
        output_chars: int,
        savings_pct: float,
        exit_code: int | None,
        outcome: str | None = None,
        config_hash: str | None = None,
    ) -> None:
        """Log a compression event to the database.

        Args:
            session_id: Current session identifier.
            command: The bash command that was run (first token only for privacy).
            filter_used: Name of the filter that was applied.
            input_chars: Character count of the original output.
            output_chars: Character count of the compressed output.
            savings_pct: Percentage savings (0-100).
            exit_code: Command exit code, if known.
            outcome: One of compressed/passthrough/no_match/filter_error, or None.
            config_hash: SHA-256 of config+filters+version, computed at mount time.
        """
        if not self.enabled:
            return
        try:
            # Only log command name (first word), never arguments, for privacy
            command_name = command.split()[0] if command else "unknown"
            timestamp = datetime.now(timezone.utc).isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO compression_log
                        (timestamp, session_id, command, filter_used,
                         input_chars, output_chars, savings_pct, exit_code,
                         outcome, config_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        session_id,
                        command_name,
                        filter_used,
                        input_chars,
                        output_chars,
                        savings_pct,
                        exit_code,
                        outcome,
                        config_hash,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"hooks-compact telemetry: Failed to log compression: {e}")

    def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """Get compression statistics for a session.

        Args:
            session_id: Session identifier to summarize.

        Returns:
            Dict with total_commands, total_input_chars, total_output_chars,
            avg_savings_pct, and breakdown_by_command.
        """
        if not self.enabled or not self._db_path.exists():
            return {}
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Overall stats
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_commands,
                        COALESCE(SUM(input_chars), 0) as total_input,
                        COALESCE(SUM(output_chars), 0) as total_output,
                        COALESCE(AVG(savings_pct), 0.0) as avg_savings
                    FROM compression_log
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()

                if not row or row["total_commands"] == 0:
                    return {}

                # Breakdown by command
                breakdown_rows = conn.execute(
                    """
                    SELECT command, COUNT(*) as count,
                           AVG(savings_pct) as avg_savings
                    FROM compression_log
                    WHERE session_id = ?
                    GROUP BY command
                    ORDER BY count DESC
                    """,
                    (session_id,),
                ).fetchall()

                return {
                    "total_commands": row["total_commands"],
                    "total_input_chars": row["total_input"],
                    "total_output_chars": row["total_output"],
                    "avg_savings_pct": round(row["avg_savings"], 1),
                    "breakdown_by_command": {
                        r["command"]: {
                            "count": r["count"],
                            "avg_savings_pct": round(r["avg_savings"], 1),
                        }
                        for r in breakdown_rows
                    },
                }
        except Exception as e:
            logger.warning(
                f"hooks-compact telemetry: Failed to get session summary: {e}"
            )
            return {}
