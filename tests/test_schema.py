from __future__ import annotations

from pathlib import Path

import pytest

from arrctl.config import Document
from arrctl.schema import validate_document


def test_example_is_valid() -> None:
    doc = Document.load(Path("examples/arr.yaml"))
    assert validate_document(doc.raw) == []


def test_unknown_field_fails(tmp_path: Path) -> None:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    config:
      ui:
        notARealField: true
"""
    )
    doc = Document.load(path)
    with pytest.raises(Exception, match="unknown field"):
        validate_document(doc.raw)


def test_allow_unknown_warns(tmp_path: Path) -> None:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    config:
      ui:
        notARealField: true
"""
    )
    doc = Document.load(path)
    warnings = validate_document(doc.raw, allow_unknown=True)
    assert warnings
