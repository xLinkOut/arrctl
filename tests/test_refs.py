from __future__ import annotations

from arrctl.refs import resolve_refs_in, resolve_refs_out


class FakeClient:
    def get(self, path: str):
        if path == "tag":
            return [{"id": 1, "label": "arrctl"}, {"id": 2, "label": "media"}]
        if path == "qualityprofile":
            return [{"id": 4, "name": "1080p ITA"}]
        return []


def test_resolve_refs_out() -> None:
    client = FakeClient()
    item = {"name": "list", "qualityProfileId": 4, "tags": [1, 2]}
    result = resolve_refs_out(client, item, {})
    assert result["qualityProfileId"] == "1080p ITA"
    assert result["tags"] == ["arrctl", "media"]


def test_resolve_refs_in() -> None:
    client = FakeClient()
    item = {"name": "list", "qualityProfileId": "1080p ITA", "tags": ["arrctl"]}
    result = resolve_refs_in(client, item, {})
    assert result["qualityProfileId"] == 4
    assert result["tags"] == [1]
