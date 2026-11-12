from __future__ import annotations

from pathlib import Path

import httpx
import respx

from arrctl.config import Document
from arrctl.engine import Engine


@respx.mock
def test_masked_secret_is_not_drift(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NTFY_TOKEN", "real-token")
    path = tmp_path / "arr.yaml"
    path.write_text(
        """
version: 1
apps:
  lidarr:
    connection:
      url: http://lidarr
      api_key: test
    resources:
      notification:
        - name: ntfy
          fields:
            accessToken: ${NTFY_TOKEN}
"""
    )
    respx.get("http://lidarr/api/v1/notification").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "ntfy",
                    "fields": [{"name": "accessToken", "value": "********"}],
                }
            ],
        )
    )
    result = Engine(Document.load(path)).plan()
    assert not any(change.field == "fields.accessToken" for change in result.changes)
