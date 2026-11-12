from __future__ import annotations

from pathlib import Path

from arrctl.config import Document
from arrctl.util import coerce_like, deep_merge, flatten_dict, resolve_value


def test_deep_merge() -> None:
    base = {"host": {"port": 8989, "logLevel": "info"}, "ui": {"theme": "auto"}}
    override = {"host": {"logLevel": "debug"}, "ui": {"theme": "dark"}}
    assert deep_merge(base, override) == {
        "host": {"port": 8989, "logLevel": "debug"},
        "ui": {"theme": "dark"},
    }


def test_resolve_env(monkeypatch) -> None:
    monkeypatch.setenv("MY_KEY", "secret")
    assert resolve_value("${MY_KEY}") == "secret"
    assert resolve_value("${MISSING:-fallback}") == "fallback"


def test_resolve_file(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("token\n")
    assert resolve_value("${file:secret.txt}", base_dir=tmp_path) == "token"


def test_coerce_like() -> None:
    assert coerce_like("8989", 8989) == 8989
    assert coerce_like("true", False) is True
    assert coerce_like("1", "x") == "1"


def test_flatten_dict() -> None:
    assert flatten_dict({"a": {"b": 1}, "c": [1, 2]}) == {"a.b": 1, "c": [1, 2]}


def test_document_merges_defaults(tmp_path: Path) -> None:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
defaults:
  ui:
    firstDayOfWeek: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    config:
      ui:
        theme: dark
"""
    )
    doc = Document.load(path)
    assert doc.merged_config("sonarr")["ui"] == {
        "firstDayOfWeek": 1,
        "theme": "dark",
    }
    assert doc.connection("sonarr").url == "http://sonarr"


def test_document_api_key_file(tmp_path: Path) -> None:
    config_xml = tmp_path / "config.xml"
    config_xml.write_text("<Config><ApiKey>abc123</ApiKey></Config>")
    path = tmp_path / "arr.yaml"
    path.write_text(
        f"""
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key_file: {config_xml}
"""
    )
    doc = Document.load(path)
    assert doc.connection("sonarr").api_key == "abc123"



