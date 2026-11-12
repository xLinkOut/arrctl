from __future__ import annotations

from pathlib import Path

import httpx
import respx

from arrctl.config import Document
from arrctl.puller import Puller


@respx.mock
def test_pull_config_and_resource(tmp_path: Path) -> None:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    # keep me
    config: {}
    resources: {}
"""
    )
    respx.get("http://sonarr/api/v3/system/status").mock(
        return_value=httpx.Response(200, json={"version": "4.0.20"})
    )
    respx.get("http://sonarr/api/v3/config/ui").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "firstDayOfWeek": 0, "theme": "dark"},
        )
    )
    respx.get("http://sonarr/api/v3/tag").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "label": "arrctl"}])
    )
    doc = Document.load(path)
    warnings = Puller(doc, only="sonarr.ui,sonarr.tag").pull()
    assert not warnings
    doc.save(path)
    text = path.read_text()
    assert "# keep me" in text
    assert "firstDayOfWeek: 0" in text
    assert "label: arrctl" in text


@respx.mock
def test_pull_omits_secrets(tmp_path: Path) -> None:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    config: {}
"""
    )
    respx.get("http://sonarr/api/v3/system/status").mock(
        return_value=httpx.Response(200, json={"version": "4.0.20"})
    )
    respx.get("http://sonarr/api/v3/config/host").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "port": 8989,
                "apiKey": "secret",
                "password": "secret",
                "proxyPassword": "",
            },
        )
    )
    doc = Document.load(path)
    Puller(doc, only="sonarr.host").pull()
    doc.save(path)
    text = path.read_text()
    assert "port: 8989" in text
    assert "secret" not in text


@respx.mock
def test_pull_bazarr_omits_secrets(tmp_path: Path) -> None:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  bazarr:
    connection:
      url: http://bazarr
      api_key: test
    config: {}
"""
    )
    respx.get("http://bazarr/api/system/status").mock(
        return_value=httpx.Response(200, json={"bazarr_version": "1.6.2"})
    )
    respx.get("http://bazarr/api/system/settings").mock(
        return_value=httpx.Response(
            200,
            json={
                "general": {"theme": "dark", "page_size": 25},
                "auth": {"apikey": "secret", "type": "form"},
            },
        )
    )
    doc = Document.load(path)
    Puller(doc, only="bazarr.general").pull()
    doc.save(path)
    text = path.read_text()
    assert "theme: dark" in text
    assert "secret" not in text


def test_infer_defaults(tmp_path: Path) -> None:
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
        firstDayOfWeek: 1
        theme: dark
  radarr:
    connection:
      url: http://radarr
      api_key: test
    config:
      ui:
        firstDayOfWeek: 1
        theme: light
"""
    )
    doc = Document.load(path)
    Puller(doc, only="sonarr.ui")._infer_defaults()
    assert doc.raw["defaults"]["ui"]["firstDayOfWeek"] == 1
    assert "firstDayOfWeek" not in doc.raw["apps"]["sonarr"]["config"]["ui"]
    assert doc.raw["apps"]["sonarr"]["config"]["ui"]["theme"] == "dark"
