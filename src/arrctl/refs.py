"""Resolve portable names to instance-specific IDs (and back)."""

from __future__ import annotations

import copy
from typing import Any

from .errors import ConfigError

# field -> (resource path, label field)
REFERENCE_MAP: dict[str, tuple[str, str]] = {
    "qualityProfileId": ("qualityprofile", "name"),
    "metadataProfileId": ("metadataprofile", "name"),
    "languageProfileId": ("languageprofile", "name"),
    "downloadClientId": ("downloadclient", "name"),
    "appProfileId": ("appprofile", "name"),
    "indexerId": ("indexer", "name"),
}

TAG_FIELD = "tags"


def _list(client: Any, path: str, cache: dict[str, list[Any]]) -> list[Any]:
    if path not in cache:
        data = client.get(path)
        cache[path] = data if isinstance(data, list) else []
    return cache[path]


def resolve_refs_out(
    client: Any, item: dict[str, Any], cache: dict[str, list[Any]]
) -> dict[str, Any]:
    """Turn live IDs into names/labels for the YAML file."""
    result = copy.deepcopy(item)
    for field, (resource, label) in REFERENCE_MAP.items():
        value = result.get(field)
        if not isinstance(value, int) or value == 0:
            continue
        for candidate in _list(client, resource, cache):
            if isinstance(candidate, dict) and candidate.get("id") == value:
                result[field] = candidate.get(label)
                break
    tags = result.get(TAG_FIELD)
    if isinstance(tags, list) and tags and all(isinstance(tag, int) for tag in tags):
        by_id = {
            candidate.get("id"): candidate.get("label")
            for candidate in _list(client, "tag", cache)
            if isinstance(candidate, dict)
        }
        result[TAG_FIELD] = [by_id.get(tag, tag) for tag in tags]
    return result


def resolve_refs_in(
    client: Any,
    item: dict[str, Any],
    cache: dict[str, list[Any]],
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Turn names/labels into live IDs before creating or updating."""
    result = copy.deepcopy(item)
    for field, (resource, label) in REFERENCE_MAP.items():
        value = result.get(field)
        if not isinstance(value, str):
            continue
        matches = [
            candidate
            for candidate in _list(client, resource, cache)
            if isinstance(candidate, dict) and candidate.get(label) == value
        ]
        if not matches:
            if strict:
                raise ConfigError(f"{field}: {label} {value!r} not found on this instance")
            continue
        result[field] = matches[0].get("id")
    tags = result.get(TAG_FIELD)
    if isinstance(tags, list) and any(isinstance(tag, str) for tag in tags):
        by_label = {
            candidate.get("label"): candidate.get("id")
            for candidate in _list(client, "tag", cache)
            if isinstance(candidate, dict)
        }
        resolved: list[Any] = []
        for tag in tags:
            if isinstance(tag, str):
                if tag not in by_label:
                    if strict:
                        raise ConfigError(f"tags: label {tag!r} not found on this instance")
                    resolved.append(tag)
                    continue
                resolved.append(by_label[tag])
            else:
                resolved.append(tag)
        result[TAG_FIELD] = resolved
    return result
