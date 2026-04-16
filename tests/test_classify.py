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
