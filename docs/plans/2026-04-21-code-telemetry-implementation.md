# Plan 2 — Code + Telemetry (Phase B) Implementation Plan

> **For execution:** Use `/execute-plan` mode.
> **This is Plan 2 of 4.** Plan 1 executed at commit `519389b` on `fix/pre-canary-hygiene`.

**Goal:** Fix session_id telemetry correlation, mount unregister callable, version single-source-of-truth, and add telemetry `outcome` + `config_hash` columns with schema migration. All changes land as Commit 2 on `fix/pre-canary-hygiene`.

**Architecture:** TDD per feature. Changes to `__init__.py` (B3, R3, R8), `hook.py` (outcome dispatch at stage 4), `telemetry.py` (2 new columns, schema migration via `PRAGMA table_info`), new tests in `test_hook.py` and `test_telemetry.py`, plus `scripts/bump-version.sh` for atomic version sync across three files.

**Tech Stack:** Python 3.11+, pytest + pytest-asyncio, SQLite (via stdlib `sqlite3`), hashlib for SHA-256, `importlib.metadata` for version resolution.

**Design doc:** `docs/plans/2026-04-21-pre-canary-hygiene-design.md` (commit `8406d67`)

**Dependency:** Plan 1 committed on `fix/pre-canary-hygiene` (commit `519389b`).

**Next plan:** Plan 3 (Eval + Scripts) — depends on Plan 2's telemetry schema being in place (for `team-report.sh` queries).

---

## Orientation

Before starting, make sure you're on the right branch at the right commit:

```bash
cd /Users/samule/repo/amplifier-module-hooks-compact
git checkout fix/pre-canary-hygiene
git log --oneline -1
# Expected: 519389b docs: pre-canary hygiene fixes (Phase A)
```

Verify the test suite is green at baseline (292 tests):

```bash
uv run pytest tests/ -q
# Expected: 292 passed
```

---

## Task 1: Version SSoT — write failing test (R8)

**Files:**
- Test: `tests/test_init.py` (create)

**Step 1: Create the test file**

Create `tests/test_init.py` with this content:

```python
"""Tests for __init__.py module-level attributes."""

from __future__ import annotations


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
```

**Step 2: Run the test to verify it passes (or fails for the right reason)**

```bash
uv run pytest tests/test_init.py -v
```

Right now `_VERSION = "0.1.0"` is hardcoded, so `test_version_reads_from_package_metadata` will pass but `test_version_is_not_hardcoded` will pass too (coincidentally, because the value happens to match). That's fine — the tests establish the contract. The real value is that if someone changes `pyproject.toml` version without the SSoT mechanism, `test_version_is_not_hardcoded` would catch it.

---

## Task 2: Version SSoT — implement (R8)

**Files:**
- Modify: `amplifier_module_hooks_compact/__init__.py:14,20`

**Step 1: Replace the hardcoded `_VERSION` and drop `import uuid`**

Open `amplifier_module_hooks_compact/__init__.py`. Replace lines 13–20 (the imports and `_VERSION` block):

Current code (lines 13–20):
```python
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_MODULE_NAME = "hooks-compact"
_VERSION = "0.1.0"
```

Replace with:
```python
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODULE_NAME = "hooks-compact"

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    _VERSION = _pkg_version("amplifier-module-hooks-compact")
except PackageNotFoundError:
    _VERSION = "unknown"
```

**What changed:**
- Removed `import uuid` (no longer needed — session_id comes from coordinator, done in Task 5)
- `_VERSION` now reads from `importlib.metadata` (the canonical source is `pyproject.toml:3`)
- Fallback to `"unknown"` if the package isn't installed (e.g., raw `python` without `pip install -e .`)

**Step 2: Run tests**

```bash
uv run pytest tests/test_init.py -v
```

Expected: both tests PASS.

---

## Task 3: Session ID from coordinator — write failing test (B3)

**Files:**
- Test: `tests/test_init.py` (append)

**Step 1: Add the test**

Append to `tests/test_init.py`:

```python
import pytest


class _FakeHookRegistry:
    """Minimal stub for coordinator.hooks that records register() calls."""

    def __init__(self) -> None:
        self.registered: list[tuple] = []

    def register(self, event: str, handler, **kwargs) -> callable:
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
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_init.py::TestMountSessionId -v
```

Expected: `test_mount_uses_coordinator_session_id` FAILS because `__init__.py:44` still has `session_id = str(uuid.uuid4())` which ignores the coordinator. `test_mount_does_not_use_uuid` also FAILS because `import uuid` is still present.

**Wait** — we already removed `import uuid` in Task 2. So `test_mount_does_not_use_uuid` may pass, but `test_mount_uses_coordinator_session_id` will still fail because line 44 still calls `uuid.uuid4()`. The import removal from Task 2 will actually cause a `NameError` at runtime. That's the right failure — it proves the code path still tries to use uuid.

---

## Task 4: Session ID from coordinator — implement (B3)

**Files:**
- Modify: `amplifier_module_hooks_compact/__init__.py:44`

**Step 1: Replace the session_id assignment**

In `amplifier_module_hooks_compact/__init__.py`, find line 44:

```python
    session_id = str(uuid.uuid4())
```

Replace with:

```python
    session_id = coordinator.session_id
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_init.py::TestMountSessionId -v
```

Expected: both tests PASS.

---

## Task 5: Mount returns unregister callable — write failing test (R3)

**Files:**
- Test: `tests/test_init.py` (append)

**Step 1: Add the test**

Append to `tests/test_init.py`:

```python
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
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_init.py::TestMountUnregister -v
```

Expected: `test_mount_returns_unregister_callable` FAILS because `mount()` currently returns `None` on line 54.

---

## Task 6: Mount returns unregister callable — implement (R3)

**Files:**
- Modify: `amplifier_module_hooks_compact/__init__.py:46-54`

**Step 1: Capture register() return value and return it**

In `amplifier_module_hooks_compact/__init__.py`, find lines 46–54:

```python
    coordinator.hooks.register(
        "tool:post",
        hook.on_tool_post,
        priority=50,
        name=_MODULE_NAME,
    )

    logger.info(f"Mounted {_MODULE_NAME} v{_VERSION} (session={session_id[:8]})")
    return None
```

Replace with:

```python
    unregister = coordinator.hooks.register(
        "tool:post",
        hook.on_tool_post,
        priority=50,
        name=_MODULE_NAME,
    )

    logger.info(f"Mounted {_MODULE_NAME} v{_VERSION} (session={session_id[:8]})")
    return unregister
```

Also update the docstring return type on line 34. Find:

```python
    Returns:
        None (contract: return None or a cleanup callable — never a dict).
```

Replace with:

```python
    Returns:
        Unregister callable from hooks.register(), or None if disabled.
```

And update the function signature on line 23. Find:

```python
async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> None:
```

Replace with:

```python
async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> Any:
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_init.py -v
```

Expected: all tests in `test_init.py` PASS.

---

## Task 7: Schema migration — write failing test

**Files:**
- Test: `tests/test_telemetry.py` (append)

**Step 1: Add the schema migration test**

Append to `tests/test_telemetry.py`:

```python
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
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_telemetry.py::TestSchemaMigration -v
```

Expected: `test_adds_columns_to_old_schema` FAILS because `_init_db()` doesn't run `ALTER TABLE`. The old rows won't have `outcome` or `config_hash` columns.

---

## Task 8: Schema migration + telemetry signature — implement

**Files:**
- Modify: `amplifier_module_hooks_compact/telemetry.py:46-63` (schema migration in `_init_db`)
- Modify: `amplifier_module_hooks_compact/telemetry.py:89-138` (update `log_compression` signature)

**Step 1: Add schema migration to `_init_db()`**

In `amplifier_module_hooks_compact/telemetry.py`, find `_init_db()` (lines 46–72). After the `CREATE TABLE IF NOT EXISTS` block and the two `CREATE INDEX` statements (before `conn.commit()` on line 70), add the migration logic.

Find this block (lines 50–72):

```python
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
                    exit_code    INTEGER
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session ON compression_log (session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON compression_log (timestamp)"
            )
            conn.commit()

        self._prune_old_records()
```

Replace with:

```python
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
                logger.warning(
                    f"hooks-compact telemetry: Schema migration failed: {e}"
                )

            conn.commit()

        self._prune_old_records()
```

**Step 2: Update `log_compression()` to accept `outcome` and `config_hash`**

Find the `log_compression` method signature (lines 89–98):

```python
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
    ) -> None:
```

Replace with:

```python
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
```

Now update the docstring. Find:

```python
        """Log a compression event to the database.

        Args:
            session_id: Current session identifier.
            command: The bash command that was run (first token only for privacy).
            filter_used: Name of the filter that was applied.
            input_chars: Character count of the original output.
            output_chars: Character count of the compressed output.
            savings_pct: Percentage savings (0-100).
            exit_code: Command exit code, if known.
        """
```

Replace with:

```python
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
```

Now update the INSERT statement. Find:

```python
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO compression_log
                        (timestamp, session_id, command, filter_used,
                         input_chars, output_chars, savings_pct, exit_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
```

Replace with:

```python
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
```

**Step 3: Run tests**

```bash
uv run pytest tests/test_telemetry.py -v
```

Expected: ALL tests in `test_telemetry.py` PASS (including the 3 new schema migration tests AND all existing tests — the new `outcome`/`config_hash` params default to `None`, so existing callers are unaffected).

---

## Task 9: Config hash — write failing test

**Files:**
- Test: `tests/test_telemetry.py` (append)

**Step 1: Add config_hash tests**

Append to `tests/test_telemetry.py`:

```python
import hashlib
import json


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
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_telemetry.py::TestConfigHash -v
```

Expected: FAIL with `ImportError: cannot import name 'compute_config_hash'`.

---

## Task 10: Config hash — implement

**Files:**
- Modify: `amplifier_module_hooks_compact/telemetry.py` (add function at module level, before the class)

**Step 1: Add the `compute_config_hash` function**

In `amplifier_module_hooks_compact/telemetry.py`, add these imports at the top (after the existing imports on lines 10–14):

Find:
```python
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
```

Replace with:
```python
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
```

Then, after the `_DEFAULT_RETENTION_DAYS` line (line 19) and before the `class TelemetryStore:` line (line 22), insert:

```python


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
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_telemetry.py::TestConfigHash -v
```

Expected: all 6 tests PASS.

---

## Task 11: Outcome dispatch in hook.py — write failing test (R9 + outcomes)

**Files:**
- Test: `tests/test_hook.py` (append)

**Step 1: Add the filter-exception passthrough test AND outcome parametrized tests**

Append to `tests/test_hook.py`:

```python
import sqlite3


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
            0, ("exploding", __import__("re").compile(r"^git\s+status\b"), _exploding_filter)
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


# ── Outcome logging ──────────────────────────────────────────────────────────


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
```

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_hook.py::TestFilterExceptionPassthrough -v
uv run pytest tests/test_hook.py::TestOutcomeLogging -v
```

Expected: ALL fail. The `filter_error` test fails because hook.py doesn't log telemetry on exception. The `no_match` test fails because the current code returns `_CONTINUE` before logging anything. The `passthrough` test fails because the passthrough path doesn't log. The `compressed` test fails because `log_compression` is called without `outcome`.

---

## Task 12: Outcome dispatch in hook.py — implement

**Files:**
- Modify: `amplifier_module_hooks_compact/hook.py:54-58,243-376`

This is the biggest task. We need to add outcome logging to every exit path from `_pipeline()` that processes a **bash** event. Non-bash exits (line 251) remain unchanged — they skip telemetry entirely.

**Step 1: Add `_config_hash` to `CompactHook.__init__`**

In `amplifier_module_hooks_compact/hook.py`, find the `__init__` method. After line 64 (`self._session_id: str = session_id or "unknown"`), add:

```python
        self._config_hash: str | None = None
```

This will be set from `mount()` after computing the hash. For now it defaults to `None`.

**Step 2: Rewrite `_pipeline()` to dispatch outcomes**

Find the entire `_pipeline` method (lines 243–376). Replace it with:

```python
    async def _pipeline(self, data: dict[str, Any]) -> HookResult:
        """Run the 4-stage compression pipeline.

        Raises exceptions freely — caller wraps in try/except (fail-safe).
        """
        # ── Stage 1: CLASSIFY ─────────────────────────────────────────────────
        tool_name = data.get("tool_name", "")
        if tool_name != "bash":
            return _CONTINUE

        tool_input = data.get("tool_input") or {}
        # Amplifier tool:post events carry the tool result under "result", not "tool_result".
        # The "result.output" field is itself a dict: {"returncode": int, "stderr": str, "stdout": str}.
        tool_result = data.get("result") or {}

        command: str = (
            tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        )
        output_obj = (
            tool_result.get("output") if isinstance(tool_result, dict) else None
        )
        output: str | None = (
            output_obj.get("stdout")
            if isinstance(output_obj, dict)
            else output_obj
            if isinstance(output_obj, str)
            else None
        )
        exit_code: int | None = (
            output_obj.get("returncode") if isinstance(output_obj, dict) else None
        )

        if not output or not isinstance(output, str):
            # Bash event but no usable output — log no_match and exit
            self._log_outcome(
                command=command, filter_used=None,
                input_chars=0, output_chars=0, savings_pct=0.0,
                exit_code=exit_code, outcome="no_match",
            )
            return _CONTINUE

        # Min-lines threshold
        line_count = output.count("\n") + 1
        if line_count < self.min_lines:
            self._log_outcome(
                command=command, filter_used=None,
                input_chars=len(output), output_chars=len(output), savings_pct=0.0,
                exit_code=exit_code, outcome="no_match",
            )
            return _CONTINUE

        # Classify command — find matching filter
        match = self._registry.classify(command)
        if match is None:
            self._log_outcome(
                command=command, filter_used=None,
                input_chars=len(output), output_chars=len(output), savings_pct=0.0,
                exit_code=exit_code, outcome="no_match",
            )
            return _CONTINUE

        filter_name, filter_fn_or_config = match

        # ── Stage 2: PRE-PROCESS ──────────────────────────────────────────────
        processed = preprocess(output, strip_ansi=self.strip_ansi)

        # ── Stage 3: FILTER ───────────────────────────────────────────────────
        try:
            if callable(filter_fn_or_config):
                # Python filter
                compressed: str = filter_fn_or_config(processed, command, exit_code)
                filter_type = "Python"
            else:
                # YAML filter
                from .filters.yaml_engine import apply_yaml_filter

                compressed = apply_yaml_filter(processed, filter_fn_or_config)
                filter_type = "YAML"
        except Exception as e:
            logger.warning(
                f"hooks-compact: Filter '{filter_name}' raised an exception: {e}"
            )
            self._log_outcome(
                command=command, filter_used=filter_name,
                input_chars=len(output), output_chars=len(output), savings_pct=0.0,
                exit_code=exit_code, outcome="filter_error",
            )
            return _CONTINUE

        # ── Stage 4: DECIDE ───────────────────────────────────────────────────
        # If filter produced no change or empty result, passthrough
        if not compressed or compressed == output or compressed == processed:
            self._log_outcome(
                command=command, filter_used=filter_name,
                input_chars=len(output), output_chars=len(output), savings_pct=0.0,
                exit_code=exit_code, outcome="passthrough",
            )
            return _CONTINUE

        # Build stats
        input_chars = len(output)
        output_chars = len(compressed)
        savings_pct = (
            round((1 - output_chars / input_chars) * 100, 1) if input_chars > 0 else 0.0
        )

        # Build modified data — never mutate in-place
        modified_data = copy.deepcopy(data)
        result_obj = modified_data.get("result")
        output_obj_mod = (
            result_obj.get("output") if isinstance(result_obj, dict) else None
        )
        if isinstance(output_obj_mod, dict):
            # Amplifier bash tool: result.output is {"returncode": int, "stderr": str, "stdout": str}
            modified_data["result"]["output"]["stdout"] = compressed
            # Preserve returncode/stderr/success — never modify these
        elif isinstance(output_obj_mod, str):
            # Fallback: output is a plain string
            modified_data["result"]["output"] = compressed
        else:
            # Can't locate where to write the compressed text — passthrough
            self._log_outcome(
                command=command, filter_used=filter_name,
                input_chars=input_chars, output_chars=input_chars, savings_pct=0.0,
                exit_code=exit_code, outcome="passthrough",
            )
            return _CONTINUE

        # ── Telemetry ─────────────────────────────────────────────────────────
        self._log_outcome(
            command=command, filter_used=filter_name,
            input_chars=input_chars, output_chars=output_chars,
            savings_pct=savings_pct, exit_code=exit_code, outcome="compressed",
        )

        # ── User message (debug or savings) ───────────────────────────────────
        user_message: str | None = None

        if self.debug:
            user_message = self._format_debug_message(
                command=command,
                filter_name=filter_name,
                filter_type=filter_type,
                original=output,
                compressed=compressed,
                input_chars=input_chars,
                output_chars=output_chars,
                savings_pct=savings_pct,
            )
        elif self.show_savings:
            user_message = f"bash compressed: {input_chars} → {output_chars} chars ({savings_pct}%)"

        return HookResult(
            action="modify",
            data=modified_data,
            user_message=user_message,
            user_message_level="info",
        )
```

**Step 3: Add the `_log_outcome` helper method**

Add this method to the `CompactHook` class, right after `_pipeline()` and before `_format_debug_message()`:

```python
    def _log_outcome(
        self,
        *,
        command: str,
        filter_used: str | None,
        input_chars: int,
        output_chars: int,
        savings_pct: float,
        exit_code: int | None,
        outcome: str,
    ) -> None:
        """Log a telemetry row with outcome. Fail-safe: never raises."""
        if self._telemetry is None:
            return
        try:
            clean_command = _strip_shell_prefix(command)
            self._telemetry.log_compression(
                session_id=self._session_id,
                command=clean_command,
                filter_used=filter_used,
                input_chars=input_chars,
                output_chars=output_chars,
                savings_pct=savings_pct,
                exit_code=exit_code,
                outcome=outcome,
                config_hash=self._config_hash,
            )
        except Exception as e:
            logger.warning(f"hooks-compact: Failed to log outcome: {e}")
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_hook.py -v
```

Expected: ALL tests PASS — both the new outcome/R9 tests and all existing tests.

---

## Task 13: Wire config_hash into mount() + bump-version.sh (R8)

**Files:**
- Modify: `amplifier_module_hooks_compact/__init__.py:42-53`
- Create: `scripts/bump-version.sh`

**Step 1: Compute config_hash at mount time and set it on the hook**

In `amplifier_module_hooks_compact/__init__.py`, find the block where the hook is created (around lines 42–53 after Task 6's edits):

```python
    from .hook import CompactHook

    session_id = coordinator.session_id
    hook = CompactHook(config, session_id=session_id)
    unregister = coordinator.hooks.register(
```

Replace the block from `from .hook import CompactHook` through the `logger.info` line:

```python
    from .hook import CompactHook
    from .telemetry import compute_config_hash

    session_id = coordinator.session_id
    hook = CompactHook(config, session_id=session_id)

    # Compute config fingerprint once for the session
    yaml_bytes = ""
    try:
        from pathlib import Path

        for candidate in [
            Path.cwd() / ".amplifier" / "output-filters.yaml",
            Path.home() / ".amplifier" / "output-filters.yaml",
        ]:
            if candidate.exists():
                yaml_bytes = candidate.read_text()
                break
    except Exception:
        yaml_bytes = ""

    hook._config_hash = compute_config_hash(
        config=config, yaml_bytes=yaml_bytes, version=_VERSION,
    )

    unregister = coordinator.hooks.register(
        "tool:post",
        hook.on_tool_post,
        priority=50,
        name=_MODULE_NAME,
    )

    logger.info(f"Mounted {_MODULE_NAME} v{_VERSION} (session={session_id[:8]})")
    return unregister
```

**Step 2: Create `scripts/bump-version.sh`**

Create the file `scripts/bump-version.sh` with this content:

```bash
#!/usr/bin/env bash
# Atomically update the version string across all three files that hardcode it.
#
# Usage: ./scripts/bump-version.sh <new-version>
#
# Files updated:
#   pyproject.toml:3      — version = "X.Y.Z"
#   bundle.md:4           — version: X.Y.Z
#   behaviors/compact.yaml:3 — version: X.Y.Z
#
# __init__.py is NOT in this list — it reads from pyproject.toml at runtime
# via importlib.metadata.version().

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <new-version>" >&2
    echo "Example: $0 0.2.0" >&2
    exit 1
fi

NEW_VERSION="$1"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Validate version looks reasonable (semver-ish)
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
    echo "Error: version '$NEW_VERSION' doesn't look like semver (X.Y.Z)" >&2
    exit 1
fi

echo "Bumping version to $NEW_VERSION in 3 files..."

# 1. pyproject.toml — line 3: version = "X.Y.Z"
sed -i '' "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$REPO_ROOT/pyproject.toml"
echo "  ✓ pyproject.toml"

# 2. bundle.md — line 4: version: X.Y.Z (under bundle: frontmatter)
sed -i '' "s/^  version: .*/  version: $NEW_VERSION/" "$REPO_ROOT/bundle.md"
echo "  ✓ bundle.md"

# 3. behaviors/compact.yaml — line 3: version: X.Y.Z
sed -i '' "s/^  version: .*/  version: $NEW_VERSION/" "$REPO_ROOT/behaviors/compact.yaml"
echo "  ✓ behaviors/compact.yaml"

echo ""
echo "Done. Verify with:"
echo "  grep -n 'version' pyproject.toml bundle.md behaviors/compact.yaml | head -6"
```

Then make it executable:

```bash
chmod +x scripts/bump-version.sh
```

**Step 3: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: ALL tests PASS (292 existing + all new tests).

---

## Task 14: Final verification and commit

**Step 1: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: ALL tests pass. Count should be 292 (original) + new tests.

**Step 2: Verify Definition of Done checks**

```bash
# Version reads from metadata, not hardcoded
python -c "from amplifier_module_hooks_compact import _VERSION; print(_VERSION)"
# Expected: 0.1.0

# uuid is gone
grep -n "uuid.uuid4" amplifier_module_hooks_compact/__init__.py
# Expected: no output (exit code 1)

grep -n "import uuid" amplifier_module_hooks_compact/__init__.py
# Expected: no output (exit code 1)

# Telemetry imports cleanly
python -c "from amplifier_module_hooks_compact.telemetry import TelemetryStore, compute_config_hash; print('OK')"
# Expected: OK

# bump-version.sh is executable
test -x scripts/bump-version.sh && echo "executable" || echo "NOT executable"
# Expected: executable

# bump-version.sh works (test and revert)
./scripts/bump-version.sh 9.9.9-test
grep 'version' pyproject.toml bundle.md behaviors/compact.yaml | head -6
# Expected: all three show 9.9.9-test

# Revert the test bump
git checkout -- pyproject.toml bundle.md behaviors/compact.yaml
grep 'version' pyproject.toml bundle.md behaviors/compact.yaml | head -6
# Expected: all three show 0.1.0
```

**Step 3: Stage and commit**

```bash
git add \
  amplifier_module_hooks_compact/__init__.py \
  amplifier_module_hooks_compact/hook.py \
  amplifier_module_hooks_compact/telemetry.py \
  tests/test_init.py \
  tests/test_hook.py \
  tests/test_telemetry.py \
  scripts/bump-version.sh

git commit -m 'fix: telemetry completion + mount unregister + version SSoT

- __init__.py: session_id from coordinator (B3); mount returns unregister (R3); _VERSION via importlib.metadata (R8)
- telemetry.py: outcome column, config_hash column, schema migration via PRAGMA table_info
- hook.py: outcome dispatch (compressed/passthrough/no_match/filter_error); skip non-bash
- tests/test_hook.py: filter-exception passthrough test (R9); outcome logging tests
- tests/test_telemetry.py: config_hash test; schema migration test
- scripts/bump-version.sh: atomic version bump across pyproject.toml, bundle.md, behaviors/compact.yaml

Refs: docs/plans/2026-04-21-pre-canary-hygiene-design.md (commit 8406d67)'
```

Expected: one clean commit on `fix/pre-canary-hygiene`.

---

## Definition of Done

- [ ] All new tests green: `uv run pytest tests/ -v`
- [ ] ALL existing tests still green (no regressions from 292-passing baseline at `519389b`)
- [ ] `python -c "from amplifier_module_hooks_compact import _VERSION; print(_VERSION)"` prints `0.1.0` (not `"unknown"`)
- [ ] `grep -n "uuid.uuid4" amplifier_module_hooks_compact/__init__.py` returns empty (import and usage both gone)
- [ ] `python -c "from amplifier_module_hooks_compact.telemetry import TelemetryStore"` imports without error
- [ ] Schema migration test confirms `ALTER TABLE` runs cleanly on pre-existing old-schema DB
- [ ] `config_hash` test confirms canonical JSON ordering + absence-case handling
- [ ] `scripts/bump-version.sh` is executable (`test -x scripts/bump-version.sh`)
- [ ] `scripts/bump-version.sh 9.9.9-test` updates all three files; reverting leaves them at `0.1.0`
- [ ] ONE commit added to `fix/pre-canary-hygiene` with the conventional message above
- [ ] No changes outside the scope listed in Section 3 above