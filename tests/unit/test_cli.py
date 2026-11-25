from aseprite_mcp import __version__
from aseprite_mcp.cli import main


def test_cli_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"aseprite-mcp {__version__}"


def test_cli_check_reports_missing_binary(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ASEPRITE_PATH", str(tmp_path / "no-such-aseprite"))

    assert main(["--check"]) == 1
    assert "ASEPRITE_PATH" in capsys.readouterr().err


def test_cli_rejects_unknown_option(capsys):
    assert main(["--frobnicate"]) == 2


def test_cli_refuses_to_start_with_a_bad_setting(monkeypatch, capsys):
    monkeypatch.setenv("ASEPRITE_MCP_SANDBOX", "enabled")

    assert main([]) == 2
    assert "ASEPRITE_MCP_SANDBOX='enabled' is not a yes/no value" in capsys.readouterr().err
