from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from arrctl.config import Document
from arrctl.engine import Engine


def _doc(tmp_path: Path, body: str) -> Document:
    path = tmp_path / "arr.yaml"
    path.write_text(body)
    return Document.load(path)


@respx.mock
def test_plan_config_change(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
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
""",
    )
    respx.get("http://sonarr/api/v3/config/ui").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1,
                "firstDayOfWeek": 0,
                "calendarWeekColumnHeader": "ddd M/D",
            },
        )
    )
    result = Engine(doc).plan()
    assert any(
        change.field == "firstDayOfWeek" and change.old == 0 and change.new == 1
        for change in result.changes
    )
    assert not any(change.requires_restart for change in result.changes)


@respx.mock
def test_apply_config_puts_full_object(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
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
""",
    )
    respx.get("http://sonarr/api/v3/config/ui").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "firstDayOfWeek": 0, "theme": "auto"},
        )
    )
    put = respx.put("http://sonarr/api/v3/config/ui/1").mock(
        return_value=httpx.Response(202, json={"id": 1})
    )
    result = Engine(doc).apply()
    assert result.changes
    payload = json.loads(put.calls[0].request.content)
    assert payload["firstDayOfWeek"] == 1
    assert payload["theme"] == "auto"


@respx.mock
def test_apply_creates_collection_item_with_schema_fields(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TOPIC", "alerts")
    doc = _doc(
        tmp_path,
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    resources:
      notification:
        - name: ntfy
          implementation: Ntfy
          configContract: NtfySettings
          onGrab: false
          fields:
            topic: ${TOPIC}
""",
    )
    respx.get("http://sonarr/api/v3/notification").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get("http://sonarr/api/v3/notification/schema").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "implementation": "Ntfy",
                    "configContract": "NtfySettings",
                    "fields": [
                        {"name": "topic", "value": "", "type": "text"},
                        {"name": "serverUrl", "value": "", "type": "text"},
                    ],
                }
            ],
        )
    )
    post = respx.post("http://sonarr/api/v3/notification").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 7,
                "name": "ntfy",
                "implementation": "Ntfy",
                "configContract": "NtfySettings",
                "fields": [
                    {"name": "topic", "value": "alerts"},
                    {"name": "serverUrl", "value": ""},
                ],
            },
        )
    )
    result = Engine(doc).apply()
    assert any(change.action == "create" for change in result.changes)
    payload = json.loads(post.calls[0].request.content)
    assert payload["name"] == "ntfy"
    fields = {entry["name"]: entry["value"] for entry in payload["fields"]}
    assert fields["topic"] == "alerts"
    assert "serverUrl" in fields


@respx.mock
def test_apply_updates_collection_fields(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    resources:
      notification:
        - name: ntfy
          onGrab: false
          fields:
            topic: alerts
""",
    )
    respx.get("http://sonarr/api/v3/notification").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 7,
                    "name": "ntfy",
                    "implementation": "Ntfy",
                    "onGrab": True,
                    "fields": [
                        {"name": "topic", "value": "old", "type": "text"},
                        {"name": "serverUrl", "value": "http://ntfy", "type": "text"},
                    ],
                }
            ],
        )
    )
    put = respx.put("http://sonarr/api/v3/notification/7").mock(
        return_value=httpx.Response(202, json={"id": 7})
    )
    result = Engine(doc).apply()
    assert any(change.field == "onGrab" for change in result.changes)
    assert any(change.field == "fields.topic" for change in result.changes)
    payload = json.loads(put.calls[0].request.content)
    fields = {entry["name"]: entry["value"] for entry in payload["fields"]}
    assert fields["topic"] == "alerts"
    assert fields["serverUrl"] == "http://ntfy"


@respx.mock
def test_bazarr_applies_form_keys(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        """
version: 1
apps:
  bazarr:
    connection:
      url: http://bazarr
      api_key: test
    config:
      general:
        theme: auto
        page_size: 50
""",
    )
    respx.get("http://bazarr/api/system/settings").mock(
        return_value=httpx.Response(
            200,
            json={"general": {"theme": "light", "page_size": 25}, "auth": {"type": "form"}},
        )
    )
    post = respx.post("http://bazarr/api/system/settings").mock(
        return_value=httpx.Response(204)
    )
    result = Engine(doc).apply()
    assert {change.field for change in result.changes} == {
        "general.theme",
        "general.page_size",
    }
    body = post.calls[0].request.content.decode()
    assert "general-theme=auto" in body
    assert "general-page_size=50" in body


@respx.mock
def test_host_change_requires_restart(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    config:
      host:
        port: 8990
""",
    )
    respx.get("http://sonarr/api/v3/config/host").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "port": 8989, "bindAddress": "*"},
        )
    )
    result = Engine(doc).plan()
    assert any(change.field == "port" and change.requires_restart for change in result.changes)


def test_invalid_resource_name(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    resources:
      doesnotexist:
        - name: x
""",
    )
    with pytest.raises(Exception, match="unknown resource"):
        Engine(doc).plan()
