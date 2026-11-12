"""Bundled schema and validation helpers."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

from .errors import ConfigError
from .util import SECRET_RE, flatten_dict

_SCHEMA: dict[str, Any] | None = None


def load_schema() -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        data = files("arrctl").joinpath("data/schema.json").read_text()
        _SCHEMA = json.loads(data)
    return _SCHEMA


def app_schema(app: str) -> dict[str, Any]:
    schema = load_schema()["apps"]
    if app not in schema:
        raise ConfigError(f"unknown app {app!r}")
    return schema[app]


def config_resources(app: str) -> list[str]:
    return list(app_schema(app)["config"].keys())


def config_fields(app: str, resource: str) -> set[str]:
    schema = app_schema(app)
    if resource not in schema["config"]:
        raise ConfigError(f"{app}: unknown config resource {resource!r}")
    return set(schema["config"][resource])


def is_secret(app: str, resource: str, field: str) -> bool:
    schema = app_schema(app)
    secrets = schema.get("secrets", {}).get(resource, [])
    if field in secrets:
        return True
    return bool(SECRET_RE.search(field.rsplit(".", 1)[-1]))


def _bazarr_allowed(key: str) -> bool:
    allowed = set(app_schema("bazarr")["config"]["settings"])
    if key in allowed:
        return True
    # Array indices are normalised: enabled_providers.0 -> enabled_providers.*
    normalised = re.sub(r"\.\d+", ".*", key)
    allowed_normalised = {re.sub(r"\.\d+", ".*", item) for item in allowed}
    if normalised in allowed_normalised:
        return True
    # A list itself is valid even when the live API exposes its elements.
    return any(item.startswith(f"{key}.") for item in allowed)


def validate_document(doc: dict[str, Any], *, allow_unknown: bool = False) -> list[str]:
    """Validate the shape of a config document.

    Returns warnings. Raises ConfigError for structural errors or unknown keys
    unless ``allow_unknown`` is set.
    """
    if not isinstance(doc, dict):
        raise ConfigError("the document must be a mapping")
    if doc.get("version") != 1:
        raise ConfigError("unsupported or missing 'version'; expected version: 1")

    warnings: list[str] = []
    defaults = doc.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be a mapping")
    for resource, values in defaults.items():
        if not isinstance(values, dict):
            raise ConfigError(f"defaults.{resource} must be a mapping")
        owners = [
            app
            for app in load_schema()["apps"]
            if app != "bazarr" and resource in load_schema()["apps"][app]["config"]
        ]
        if not owners:
            msg = f"defaults.{resource}: no app supports this resource"
            if allow_unknown:
                warnings.append(msg)
                continue
            raise ConfigError(msg)
        valid = set().union(*(config_fields(app, resource) for app in owners))
        for key in values:
            if key == "id":
                continue
            if key not in valid:
                msg = f"defaults.{resource}.{key}: unknown field"
                if allow_unknown:
                    warnings.append(msg)
                else:
                    raise ConfigError(msg)

    apps = doc.get("apps")
    if not isinstance(apps, dict) or not apps:
        raise ConfigError("'apps' must be a non-empty mapping")

    known_apps = set(load_schema()["apps"])
    for app, app_doc in apps.items():
        if app not in known_apps:
            raise ConfigError(f"unknown app {app!r}; known apps: {', '.join(sorted(known_apps))}")
        if not isinstance(app_doc, dict):
            raise ConfigError(f"apps.{app} must be a mapping")

        config = app_doc.get("config", {})
        if not isinstance(config, dict):
            raise ConfigError(f"apps.{app}.config must be a mapping")
        for resource, values in config.items():
            if not isinstance(values, dict):
                raise ConfigError(f"apps.{app}.config.{resource} must be a mapping")
            if app == "bazarr":
                for key, value in flatten_dict(values).items():
                    full_key = f"{resource}.{key}"
                    if _bazarr_allowed(full_key):
                        continue
                    # Empty lists are normal Bazarr settings (the live API
                    # exposes no leaf value for them).
                    if isinstance(value, list):
                        continue
                    msg = f"{app}.config.{full_key}: unknown setting"
                    if allow_unknown:
                        warnings.append(msg)
                    else:
                        raise ConfigError(msg)
                continue
            try:
                fields = config_fields(app, resource)
            except ConfigError:
                msg = f"{app}.config.{resource}: unknown config resource"
                if allow_unknown:
                    warnings.append(msg)
                    continue
                raise
            for key in values:
                if key == "id":
                    continue
                if key not in fields:
                    msg = f"{app}.config.{resource}.{key}: unknown field"
                    if allow_unknown:
                        warnings.append(msg)
                    else:
                        raise ConfigError(msg)

        resources = app_doc.get("resources", {})
        if not isinstance(resources, dict):
            raise ConfigError(f"apps.{app}.resources must be a mapping")
        if app == "bazarr" and resources:
            raise ConfigError("Bazarr does not expose collection resources in arrctl yet")
        for resource, items in resources.items():
            if not isinstance(items, list):
                raise ConfigError(f"apps.{app}.resources.{resource} must be a list")
            if not items:
                continue
            if not isinstance(items[0], dict):
                raise ConfigError(f"apps.{app}.resources.{resource}[0] must be a mapping")
    return warnings
