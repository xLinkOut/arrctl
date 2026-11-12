from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arrctl.cli import app

runner = CliRunner()


def test_validate_example() -> None:
    result = runner.invoke(app, ["validate", "-c", "examples/arr.yaml"])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_init_writes_template(tmp_path: Path) -> None:
    output = tmp_path / "arr.yaml"
    result = runner.invoke(app, ["init", "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "version: 1" in output.read_text()


def test_schema_ui() -> None:
    result = runner.invoke(app, ["schema", "sonarr", "ui"])
    assert result.exit_code == 0, result.output
    assert "firstDayOfWeek" in result.output


def test_schema_unknown_app() -> None:
    result = runner.invoke(app, ["schema", "nope"])
    assert result.exit_code == 1
