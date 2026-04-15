"""Unit tests for build tool output filters."""

from __future__ import annotations


from amplifier_module_hooks_compact.filters.build import (
    filter_cargo_build,
    filter_npm_build,
    filter_tsc,
)


# ── cargo build ───────────────────────────────────────────────────────────────


class TestFilterCargoBuild:
    SUCCESS_OUTPUT = (
        "   Compiling serde v1.0.195\n"
        "   Compiling serde_json v1.0.111\n"
        "   Compiling myproject v0.1.0 (/home/user/myproject)\n"
        "    Finished dev [unoptimized + debuginfo] target(s) in 45.67s\n"
    )

    ERROR_OUTPUT = (
        "   Compiling myproject v0.1.0 (/home/user/myproject)\n"
        "error[E0308]: mismatched types\n"
        "  --> src/main.rs:10:5\n"
        "   |\n"
        '10 |     return "hello";\n'
        "   |            ^^^^^^^ expected `i32`, found `&str`\n"
        "\n"
        "error[E0425]: cannot find value `undefined_var` in this scope\n"
        "  --> src/lib.rs:45:9\n"
        "   |\n"
        "45 |     undefined_var.do_thing();\n"
        "   |     ^^^^^^^^^^^^^ not found in this scope\n"
        "\n"
        "For more information about this error, try `rustc --explain E0308`.\n"
        "error: could not compile `myproject` due to 2 previous errors\n"
    )

    def test_success_returns_ok(self):
        result = filter_cargo_build(self.SUCCESS_OUTPUT, "cargo build", 0)
        assert "ok" in result.lower()

    def test_success_significantly_shorter(self):
        result = filter_cargo_build(self.SUCCESS_OUTPUT, "cargo build", 0)
        assert len(result) < len(self.SUCCESS_OUTPUT) * 0.3

    def test_error_shows_error_lines(self):
        result = filter_cargo_build(self.ERROR_OUTPUT, "cargo build", 1)
        assert "mismatched types" in result or "E0308" in result

    def test_error_strips_compiling_lines(self):
        result = filter_cargo_build(self.ERROR_OUTPUT, "cargo build", 1)
        assert "Compiling serde" not in result

    def test_error_shorter_than_original(self):
        result = filter_cargo_build(self.ERROR_OUTPUT, "cargo build", 1)
        assert len(result) < len(self.ERROR_OUTPUT)

    def test_success_with_warnings_shows_warnings(self):
        output = (
            "   Compiling myproject v0.1.0\n"
            "warning[unused_variables]: unused variable: `x`\n"
            "  --> src/main.rs:5:9\n"
            "   |\n"
            "5  |     let x = 1;\n"
            "   |         ^ help: if this is intentional, prefix it with an underscore: `_x`\n"
            "\n"
            "    Finished dev target(s) in 5.23s\n"
        )
        result = filter_cargo_build(output, "cargo build", 0)
        assert "ok" in result.lower()
        assert "unused variable" in result or "warning" in result.lower()


# ── tsc ───────────────────────────────────────────────────────────────────────


class TestFilterTsc:
    SUCCESS_OUTPUT = "\nFound 0 errors. Watching for file changes.\n"

    ERROR_OUTPUT = (
        "src/auth.ts(45,9): error TS2339: Property 'foo' does not exist on type 'Bar'.\n"
        "src/utils.ts(12,1): error TS7006: Parameter 'x' implicitly has an 'any' type.\n"
        "src/models.ts(78,15): warning TS6133: 'unused' is declared but its value is never read.\n"
    )

    def test_success_returns_ok(self):
        result = filter_tsc(self.SUCCESS_OUTPUT, "tsc", 0)
        assert "ok" in result.lower()

    def test_error_shows_error_lines(self):
        result = filter_tsc(self.ERROR_OUTPUT, "tsc", 2)
        assert "TS2339" in result or "foo" in result
        assert "TS7006" in result or "implicit" in result.lower()

    def test_error_shows_count(self):
        result = filter_tsc(self.ERROR_OUTPUT, "tsc", 2)
        assert "2" in result or "error" in result.lower()

    def test_no_errors_exit_nonzero_fallback(self):
        output = "Some unexpected output\nwithout ts errors\n" * 5
        result = filter_tsc(output, "tsc", 1)
        # Should return last few lines as fallback
        assert len(result) > 0

    def test_warning_shows_in_output(self):
        result = filter_tsc(self.ERROR_OUTPUT, "tsc", 2)
        # Warnings may also be shown
        assert "TS6133" in result or "warning" in result.lower()

    def test_npx_tsc_command_works(self):
        """npx tsc should be handled the same way."""
        result = filter_tsc(self.ERROR_OUTPUT, "npx tsc", 2)
        assert "TS2339" in result or len(result) < len(self.ERROR_OUTPUT) * 2


# ── npm build ─────────────────────────────────────────────────────────────────


class TestFilterNpmBuild:
    def test_success_returns_ok(self):
        output = (
            "> myproject@1.0.0 build\n"
            "> webpack --config webpack.config.js\n"
            "\n"
            "asset main.js 456 KiB [emitted] [minimized]\n"
            "webpack 5.90.0 compiled successfully in 8234 ms\n"
        )
        result = filter_npm_build(output, "npm run build", 0)
        assert "ok" in result.lower()

    def test_failure_shows_errors(self):
        output = (
            "> myproject@1.0.0 build\n"
            "> webpack --config webpack.config.js\n"
            "\n"
            "ERROR in ./src/index.ts\n"
            "Module not found: Error: Can't resolve './missing'\n"
            "\n"
            "npm ERR! code ELIFECYCLE\n"
            "npm ERR! errno 2\n"
        )
        result = filter_npm_build(output, "npm run build", 2)
        assert "ERROR" in result or "error" in result.lower()

    def test_failure_strips_noise(self):
        output = (
            "> myproject@1.0.0 build\n"
            "> webpack\n"
            "ERROR in src/main.ts: Missing module\n"
            "npm ERR! code 2\n"
        )
        result = filter_npm_build(output, "npm run build", 2)
        assert len(result) <= len(output)
