from __future__ import annotations

from pathlib import Path

import httpx
import respx

from arrctl.config import Document
from arrctl.engine import Engine


def _doc(tmp_path: Path) -> Document:
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  sonarr:
    connection:
      url: http://sonarr
      api_key: test
    resources:
      tag:
        - label: arrctl
      notification:
        - name: ntfy
          tags:
            - arrctl
          fields:
            topic: alerts
"""
    )
    return Document.load(path)


@respx.mock
def test_plan_tolerates_missing_reference(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    respx.get("http://sonarr/api/v3/tag").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get("http://sonarr/api/v3/notification").mock(
        return_value=httpx.Response(200, json=[])
    )
    result = Engine(doc).plan()
    assert any(change.resource == "tag" for change in result.changes)
    assert any(change.resource == "notification" for change in result.changes)


@respx.mock
def test_apply_creates_tag_before_referencing_it(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    responses = iter(
        [
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[{"id": 5, "label": "arrctl"}]),
        ]
    )
    respx.get("http://sonarr/api/v3/tag").mock(side_effect=lambda request: next(responses))
    respx.get("http://sonarr/api/v3/notification").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get("http://sonarr/api/v3/notification/schema").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "implementation": None,
                    "configContract": None,
                    "fields": [{"name": "topic", "value": "", "type": "text"}],
                }
            ],
        )
    )
    post_tag = respx.post("http://sonarr/api/v3/tag").mock(
        return_value=httpx.Response(201, json={"id": 5, "label": "arrctl"})
    )
    post_notification = respx.post("http://sonarr/api/v3/notification").mock(
        return_value=httpx.Response(201, json={"id": 7, "name": "ntfy"})
    )
    result = Engine(doc).apply()
    assert post_tag.called
    assert post_notification.called
    payload = __import__("json").loads(post_notification.calls[0].request.content)
    assert payload["tags"] == [5]
    assert result.changes
