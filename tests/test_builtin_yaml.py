"""Tests for the 5 built-in YAML filter files.

Loads each filter from builtin_filters/ and applies it to representative
command output to verify the filtering rules work as documented.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from amplifier_module_hooks_compact.filters.yaml_engine import apply_yaml_filter

BUILTIN_DIR = (
    Path(__file__).parent.parent / "amplifier_module_hooks_compact" / "builtin_filters"
)


def _load(name: str) -> dict:
    """Load a built-in YAML filter by file stem."""
    with open(BUILTIN_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f)


# ── make ────────────────────────────────────────────────────────────────────


class TestMakeFilter:
    def test_strips_entering_directory_lines(self) -> None:
        """make[N]: Entering directory ... lines are stripped."""
        config = _load("make")
        output = "\n".join(
            [
                "make[1]: Entering directory '/home/user/project'",
                "gcc -c main.c -o main.o",
                "make[1]: Leaving directory '/home/user/project'",
                "make[2]: Entering directory '/home/user/project/src'",
                "gcc -c util.c -o util.o",
            ]
            * 4  # duplicate to exceed any min-line checks
        )
        result = apply_yaml_filter(output, config)
        assert "Entering directory" not in result
        assert "Leaving directory" not in result
        assert "gcc" in result

    def test_on_empty_fallback_when_only_noise(self) -> None:
        """When all lines are make-directory noise, on_empty='make: ok' is returned."""
        config = _load("make")
        output = "\n".join(["make[1]: Entering directory '/tmp'"] * 10)
        result = apply_yaml_filter(output, config)
        assert result == "make: ok"

    def test_max_lines_truncates_long_output(self) -> None:
        """make filter caps output at max_lines lines."""
        config = _load("make")
        max_lines = config["max_lines"]
        # Build output that is well over the limit; all lines kept by strip
        output = "\n".join([f"compile step {i}" for i in range(max_lines + 20)])
        result = apply_yaml_filter(output, config)
        result_lines = result.split("\n")
        assert len(result_lines) <= max_lines + 1  # +1 for the truncation marker


# ── brew ────────────────────────────────────────────────────────────────────


class TestBrewFilter:
    def test_replaces_already_installed_warning(self) -> None:
        """'Warning: X already installed' is replaced with the short form."""
        config = _load("brew")
        output = "Warning: foo already installed\n==> Summary"
        result = apply_yaml_filter(output, config)
        assert "Warning: foo already installed" not in result
        assert "already installed" in result

    def test_strips_fetching_line(self) -> None:
        """'==> Fetching ...' lines are stripped."""
        config = _load("brew")
        output = "==> Fetching dependencies\nInstalled foo"
        result = apply_yaml_filter(output, config)
        assert "Fetching" not in result
        assert "Installed foo" in result

    def test_strips_downloading_line(self) -> None:
        """'==> Downloading ...' lines are stripped."""
        config = _load("brew")
        output = "==> Downloading https://example.com/pkg.tar.gz\nInstalled foo"
        result = apply_yaml_filter(output, config)
        assert "Downloading" not in result
        assert "Installed foo" in result

    def test_strips_progress_bar_lines(self) -> None:
        """'### ...' progress bar lines are stripped."""
        config = _load("brew")
        output = "### progress ###\nInstalled foo"
        result = apply_yaml_filter(output, config)
        assert "### progress" not in result
        assert "Installed foo" in result

    def test_on_empty_fallback(self) -> None:
        """When all lines are stripped, on_empty='brew: ok' is returned."""
        config = _load("brew")
        # Only blank lines remain after an otherwise empty brew run
        output = "\n\n\n"
        result = apply_yaml_filter(output, config)
        assert result == "brew: ok"


# ── docker ───────────────────────────────────────────────────────────────────


class TestDockerFilter:
    def test_strips_layer_hash_lines(self) -> None:
        """' ---> <hash>' layer hash lines are stripped."""
        config = _load("docker")
        output = (
            " ---> abc123def456\n"
            "Step 1/5 : FROM python:3.11\n"
            "Successfully built abc123\n"
        )
        result = apply_yaml_filter(output, config)
        assert "--->" not in result
        assert "Step 1/5" in result
        assert "Successfully built" in result

    def test_strips_using_cache_lines(self) -> None:
        """' Using cache' lines are stripped."""
        config = _load("docker")
        output = (
            " Using cache\n"
            "Step 2/5 : RUN pip install flask\n"
            "Successfully tagged myimage:latest\n"
        )
        result = apply_yaml_filter(output, config)
        assert "Using cache" not in result
        assert "Successfully tagged" in result

    def test_strips_removing_intermediate_container(self) -> None:
        """'Removing intermediate container ...' lines are stripped."""
        config = _load("docker")
        output = (
            "Removing intermediate container abc123\n"
            "Step 3/5 : COPY . /app\n"
            "Successfully built abc123\n"
        )
        result = apply_yaml_filter(output, config)
        assert "Removing intermediate container" not in result
        assert "Successfully built" in result

    def test_tail_lines_applied(self) -> None:
        """docker filter keeps only the last tail_lines lines of output."""
        config = _load("docker")
        tail_n = config["tail_lines"]
        output = "\n".join([f"step {i}" for i in range(tail_n + 30)])
        result = apply_yaml_filter(output, config)
        result_lines = result.split("\n")
        assert len(result_lines) <= tail_n + 1  # +1 for possible separator

    def test_on_empty_fallback(self) -> None:
        """When all lines are stripped, on_empty='docker build: ok' is returned."""
        config = _load("docker")
        # Only cache/hash lines
        output = " ---> abc123\n Using cache\n ---> def456\n Using cache"
        result = apply_yaml_filter(output, config)
        assert result == "docker build: ok"


# ── pip ──────────────────────────────────────────────────────────────────────


class TestPipFilter:
    def test_strips_downloading_line(self) -> None:
        """'  Downloading ...' progress lines are stripped."""
        config = _load("pip")
        output = (
            "  Downloading requests-2.31.0-py3-none-any.whl (62 kB)\n"
            "Successfully installed requests-2.31.0\n"
        )
        result = apply_yaml_filter(output, config)
        assert "Downloading" not in result
        assert "Successfully installed" in result

    def test_strips_using_cached_line(self) -> None:
        """'  Using cached ...' lines are stripped."""
        config = _load("pip")
        output = (
            "  Using cached requests-2.31.0-py3-none-any.whl (62 kB)\n"
            "Successfully installed requests-2.31.0\n"
        )
        result = apply_yaml_filter(output, config)
        assert "Using cached" not in result
        assert "Successfully installed" in result

    def test_strips_requirement_already_satisfied(self) -> None:
        """'Requirement already satisfied: ...' lines are stripped."""
        config = _load("pip")
        output = (
            "Requirement already satisfied: requests in /usr/lib/python3\n"
            "Requirement already satisfied: urllib3 in /usr/lib/python3\n"
            "Successfully installed foo-1.0\n"
        )
        result = apply_yaml_filter(output, config)
        assert "Requirement already satisfied" not in result
        assert "Successfully installed" in result

    def test_on_empty_fallback(self) -> None:
        """When all lines are stripped, on_empty='pip: ok (nothing changed)' is returned."""
        config = _load("pip")
        # Only "already satisfied" and blank lines
        output = (
            "Requirement already satisfied: foo in /usr\n"
            "\n"
            "Requirement already satisfied: bar in /usr\n"
        )
        result = apply_yaml_filter(output, config)
        assert result == "pip: ok (nothing changed)"


# ── curl ─────────────────────────────────────────────────────────────────────


class TestCurlFilter:
    def test_strips_trying_line(self) -> None:
        """'* Trying ...' connection lines are stripped."""
        config = _load("curl")
        output = '* Trying 93.184.216.34:443...\n{"status": "ok"}\n'
        result = apply_yaml_filter(output, config)
        assert "Trying" not in result
        assert '{"status": "ok"}' in result

    def test_strips_tls_ssl_lines(self) -> None:
        """'* TLS ...' and '* SSL ...' handshake lines are stripped."""
        config = _load("curl")
        output = (
            "* TLS 1.3 connection using TLS_AES_128_GCM_SHA256\n"
            "* SSL certificate verify ok.\n"
            '{"data": "value"}\n'
        )
        result = apply_yaml_filter(output, config)
        assert "TLS" not in result
        assert "SSL" not in result
        assert '{"data": "value"}' in result

    def test_strips_verbose_request_response_headers(self) -> None:
        """Lines starting with '> ' or '< ' (verbose headers) are stripped."""
        config = _load("curl")
        output = (
            "> GET / HTTP/1.1\n"
            "> Host: example.com\n"
            "< HTTP/1.1 200 OK\n"
            "< Content-Type: application/json\n"
            '{"result": "success"}\n'
        )
        result = apply_yaml_filter(output, config)
        lines = result.split("\n")
        assert not any(line.startswith("> ") for line in lines)
        assert not any(line.startswith("< ") for line in lines)
        assert '{"result": "success"}' in result

    def test_strips_connected_line(self) -> None:
        """'* Connected to ...' lines are stripped."""
        config = _load("curl")
        output = "* Connected to example.com (93.184.216.34) port 443\nresponse body\n"
        result = apply_yaml_filter(output, config)
        assert "Connected" not in result
        assert "response body" in result

    def test_on_empty_fallback(self) -> None:
        """When all lines are stripped, on_empty='curl: ok (empty response)' is returned."""
        config = _load("curl")
        # Only verbose headers and blank lines
        output = "> GET / HTTP/1.1\n< HTTP/1.1 204 No Content\n\n"
        result = apply_yaml_filter(output, config)
        assert result == "curl: ok (empty response)"
