"""Tests for filter registry and command classification."""

from __future__ import annotations


from amplifier_module_hooks_compact.filters import FilterRegistry


class TestFilterRegistry:
    def test_empty_registry_returns_none(self):
        registry = FilterRegistry()
        assert registry.classify("git status") is None

    def test_registers_and_matches_python_filter(self):
        registry = FilterRegistry()

        def mock_filter(output, cmd, exit_code):
            return output

        registry.register_python("git-status", r"^git\s+status", mock_filter)

        result = registry.classify("git status")
        assert result is not None
        assert result[0] == "git-status"

    def test_python_filter_priority_over_yaml(self):
        """Python filters match before built-in YAML filters."""
        registry = FilterRegistry()

        def py_filter(output, cmd, exit_code):
            return "python"

        registry.register_python("git-py", r"^git\b", py_filter)
        registry.register_yaml("git-yaml", {"match_command": r"^git\b"})

        result = registry.classify("git status")
        assert result is not None
        name, _ = result
        assert name == "git-py"

    def test_no_match_returns_none(self):
        registry = FilterRegistry()
        registry.register_python("git-status", r"^git\s+status", lambda o, c, e: o)

        assert registry.classify("cargo test") is None

    def test_yaml_filter_matches_when_no_python(self):
        registry = FilterRegistry()
        config = {"match_command": r"^make\b", "on_empty": "ok"}
        registry.register_yaml("make", config)

        result = registry.classify("make all")
        assert result is not None
        name, returned_config = result
        assert name == "make"
        assert returned_config == config

    def test_user_yaml_priority_over_python(self):
        """User YAML filters have higher priority than Python filters."""
        registry = FilterRegistry()

        def py_filter(output, cmd, exit_code):
            return "python"

        registry.register_python("git-py", r"^git\b", py_filter)
        user_config = {"match_command": r"^git\b", "on_empty": "user-yaml"}
        registry.register_user_yaml("git-user", r"^git\b", user_config)

        result = registry.classify("git status")
        assert result is not None
        name, _ = result
        assert name == "git-user"

    def test_returns_callable_for_python_filter(self):
        registry = FilterRegistry()

        def fn(output, cmd, exit_code):
            return output

        registry.register_python("test-filter", r"^test\b", fn)

        match = registry.classify("test command")
        assert match is not None
        name, fn_result = match
        assert callable(fn_result)

    def test_returns_dict_for_yaml_filter(self):
        registry = FilterRegistry()
        config = {"match_command": r"^make\b", "max_lines": 10}
        registry.register_yaml("make", config)

        match = registry.classify("make clean")
        assert match is not None
        name, result = match
        assert isinstance(result, dict)

    def test_first_match_wins(self):
        """When multiple patterns match, first registered wins."""
        registry = FilterRegistry()

        def fn1(o, c, e):
            return "first"

        def fn2(o, c, e):
            return "second"

        registry.register_python("first", r"^git\b", fn1)
        registry.register_python("second", r"^git\s+status\b", fn2)

        result = registry.classify("git status")
        assert result is not None
        name, _ = result
        assert name == "first"

    def test_pattern_is_a_search_not_fullmatch(self):
        """Pattern is searched within command string, not full-matched."""
        registry = FilterRegistry()

        def fn(o, c, e):
            return o

        registry.register_python("cargo-test", r"cargo\s+test", fn)

        # Pattern found within a longer command
        result = registry.classify("cd myproject && cargo test --release")
        assert result is not None
        assert result[0] == "cargo-test"

    def test_yaml_filter_without_match_command_is_skipped(self):
        """YAML filters missing match_command should not be registered."""
        registry = FilterRegistry()
        registry.register_yaml("no-pattern", {"max_lines": 10, "on_empty": "ok"})

        assert registry.classify("anything") is None

    # ------------------------------------------------------------------
    # cd-prefix stripping (Amplifier bash tool prepends "cd /path &&")
    # ------------------------------------------------------------------

    def test_cd_prefix_and_ampersand_matches_git_status(self):
        """cd /path && git status should match git-status filter."""
        registry = FilterRegistry()
        registry.register_python("git-status", r"^git\s+status\b", lambda o, c, e: o)

        result = registry.classify(
            "cd /Users/samule/repo/teamkb-workspace && git status"
        )
        assert result is not None
        assert result[0] == "git-status"

    def test_cd_prefix_and_ampersand_matches_cargo_test(self):
        """cd /path && cargo test should match cargo-test filter."""
        registry = FilterRegistry()
        registry.register_python("cargo-test", r"^cargo\s+test\b", lambda o, c, e: o)

        result = registry.classify("cd /Users/samule/repo && cargo test")
        assert result is not None
        assert result[0] == "cargo-test"

    def test_cd_prefix_semicolon_matches_git_status(self):
        """cd /path; git status should match git-status filter."""
        registry = FilterRegistry()
        registry.register_python("git-status", r"^git\s+status\b", lambda o, c, e: o)

        result = registry.classify("cd /some/path; git status")
        assert result is not None
        assert result[0] == "git-status"

    def test_chained_cd_prefix_matches_git_diff(self):
        """cd /a && cd /b && git diff should match git-diff filter."""
        registry = FilterRegistry()
        registry.register_python("git-diff", r"^git\s+diff\b", lambda o, c, e: o)

        result = registry.classify("cd /a && cd /b && git diff")
        assert result is not None
        assert result[0] == "git-diff"


class TestCompoundCommandPassthrough:
    """Compound commands (containing && after cd-stripping) must passthrough.

    When the model chains multiple commands with &&, the hook should NOT apply
    a filter to the combined output. Doing so strips output from the later
    commands, causing the model to retry — which adds extra tool calls.

    Examples that should NOT be compressed:
      - git status && git log --oneline -10 && git diff
      - cd /path && git status && git diff   (cd stripped, still has &&)
      - pytest test_a.py && pytest test_b.py
    """

    def _make_hook(self):
        from amplifier_module_hooks_compact.hook import CompactHook

        return CompactHook({"enabled": True, "min_lines": 5})

    def test_compound_git_status_and_log_returns_none(self):
        """git status && git log --oneline -10 must not be compressed."""
        hook = self._make_hook()
        result = hook._registry.classify(
            "git status && git log --oneline -10 && git diff"
        )
        assert result is None, (
            "compound git command should not match — would strip git log output"
        )

    def test_compound_git_with_echo_separator_returns_none(self):
        """Compound command with echo separators must not be compressed."""
        hook = self._make_hook()
        result = hook._registry.classify(
            'git status && echo "---" && git log --oneline -10 && echo "---" && git diff'
        )
        assert result is None

    def test_compound_after_cd_strip_returns_none(self):
        """cd /path && git status && git diff: after cd strip still has &&, must be None."""
        hook = self._make_hook()
        result = hook._registry.classify(
            "cd /Users/samule/repo && git status && git diff"
        )
        assert result is None

    def test_single_git_status_after_cd_still_matches(self):
        """cd /path && git status (no extra &&): must still be compressed."""
        hook = self._make_hook()
        result = hook._registry.classify(
            "cd /Users/samule/repo/amplifier-module-hooks-compact && git status"
        )
        assert result is not None
        assert result[0] == "git-status"

    def test_single_pytest_after_cd_still_matches(self):
        """cd /path && uv run pytest: must still be compressed."""
        hook = self._make_hook()
        result = hook._registry.classify(
            "cd /Users/samule/repo/amplifier-module-hooks-compact && uv run pytest -q"
        )
        assert result is not None
        assert result[0] == "pytest"

    def test_piped_pytest_still_matches(self):
        """pytest ... | tail -50 uses pipe not &&, must still match pytest filter."""
        hook = self._make_hook()
        result = hook._registry.classify(
            "cd /Users/samule/repo && uv run pytest 2>&1 | tail -50"
        )
        assert result is not None
        assert result[0] == "pytest"

    def test_semicolon_compound_returns_none(self):
        """git status ; git log: semicolon compound should not be compressed."""
        hook = self._make_hook()
        result = hook._registry.classify("git status ; git log --oneline -10")
        assert result is None


class TestPytestPatternCoverage:
    """Verify the pytest pattern in CompactHook covers common invocations."""

    def _make_hook(self):
        from amplifier_module_hooks_compact.hook import CompactHook

        return CompactHook({"enabled": True, "min_lines": 5})

    def test_bare_pytest(self):
        hook = self._make_hook()
        result = hook._registry.classify("pytest tests/")
        assert result is not None
        assert result[0] == "pytest"

    def test_uv_run_pytest(self):
        hook = self._make_hook()
        result = hook._registry.classify("uv run pytest -q")
        assert result is not None
        assert result[0] == "pytest"

    def test_python_m_pytest(self):
        hook = self._make_hook()
        result = hook._registry.classify("python -m pytest tests/")
        assert result is not None
        assert result[0] == "pytest"

    def test_python3_m_pytest(self):
        """python3 -m pytest should match (new in this release)."""
        hook = self._make_hook()
        result = hook._registry.classify("python3 -m pytest tests/")
        assert result is not None
        assert result[0] == "pytest"

    def test_poetry_run_pytest(self):
        """poetry run pytest should match (new in this release)."""
        hook = self._make_hook()
        result = hook._registry.classify("poetry run pytest")
        assert result is not None
        assert result[0] == "pytest"

    def test_cd_prefix_uv_run_pytest(self):
        hook = self._make_hook()
        result = hook._registry.classify(
            "cd /Users/samule/repo/amplifier-module-hooks-compact && uv run pytest -q"
        )
        assert result is not None
        assert result[0] == "pytest"

    def test_cd_prefix_python3_m_pytest(self):
        hook = self._make_hook()
        result = hook._registry.classify("cd /repo && python3 -m pytest tests/ -v")
        assert result is not None
        assert result[0] == "pytest"


class TestToolRunnerPrefixStripping:
    """Tests for tool runner prefix stripping: uvx, npx, bunx, etc.

    These patterns appear when the model uses package managers to run tools
    rather than calling the tool binary directly.
    """

    def _make_hook(self):
        from amplifier_module_hooks_compact.hook import CompactHook

        return CompactHook({"enabled": True, "min_lines": 5})

    # ── uvx ──────────────────────────────────────────────────────────────────

    def test_uvx_ruff_matches_ruff_filter(self):
        """uvx ruff check is the real-world command — must match ruff filter."""
        hook = self._make_hook()
        result = hook._registry.classify("uvx ruff check /tmp/file.py")
        assert result is not None, "uvx ruff check should match a filter"
        assert result[0] == "ruff", f"Expected 'ruff' filter, got {result[0]!r}"

    def test_uvx_pytest_matches_pytest_filter(self):
        """uvx pytest should match pytest filter."""
        hook = self._make_hook()
        result = hook._registry.classify("uvx pytest tests/")
        assert result is not None
        assert result[0] == "pytest"

    def test_cd_prefix_plus_uvx_ruff(self):
        """cd /path && uvx ruff check should match ruff filter."""
        hook = self._make_hook()
        result = hook._registry.classify(
            "cd /Users/samule/repo && uvx ruff check /tmp/lint_issues.py"
        )
        assert result is not None
        assert result[0] == "ruff"

    # ── npx ──────────────────────────────────────────────────────────────────

    def test_npx_eslint_matches_eslint_filter(self):
        """npx eslint should match eslint filter."""
        hook = self._make_hook()
        result = hook._registry.classify("npx eslint src/")
        assert result is not None
        assert result[0] == "eslint"

    # ── bunx ─────────────────────────────────────────────────────────────────

    def test_bunx_vitest_matches_npm_test_filter(self):
        """bunx vitest should match npm-test filter (vitest detected inside)."""
        hook = self._make_hook()
        result = hook._registry.classify("bunx vitest run")
        # vitest/npm_test filter should match
        assert result is not None, "bunx vitest should match a test filter"

    # ── _strip_shell_prefix directly ─────────────────────────────────────────

    def test_strip_uvx(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("uvx ruff check .") == "ruff check ."

    def test_strip_uv_run(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("uv run pytest -v") == "pytest -v"

    def test_strip_npx(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("npx eslint src/") == "eslint src/"

    def test_strip_poetry_run(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("poetry run pytest") == "pytest"

    def test_strip_python_m(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("python -m pytest") == "pytest"

    def test_strip_python3_m(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("python3 -m ruff check .") == "ruff check ."

    def test_strip_cd_then_uvx(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("cd /path && uvx ruff check .") == "ruff check ."

    def test_no_prefix_unchanged(self):
        from amplifier_module_hooks_compact.filters import _strip_shell_prefix

        assert _strip_shell_prefix("git status") == "git status"
