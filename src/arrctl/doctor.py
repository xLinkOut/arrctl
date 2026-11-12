"""Connectivity and schema drift checks."""

from __future__ import annotations

from .client import BazarrClient, ServarrClient
from .config import Document
from .errors import ApiError, ArrctlError, ConfigError
from .schema import app_schema, config_fields
from .util import flatten_dict


def run_doctor(document: Document) -> tuple[list[str], list[str]]:
    """Return (messages, problems)."""
    messages: list[str] = []
    problems: list[str] = []
    for app in document.apps:
        try:
            connection = document.connection(app)
        except ConfigError as exc:
            problems.append(str(exc))
            continue
        if app == "bazarr":
            bazarr_client = BazarrClient(connection)
            try:
                status = bazarr_client.get("api/system/status")
                version = (
                    status.get("bazarr_version", "unknown")
                    if isinstance(status, dict)
                    else "unknown"
                )
                messages.append(f"{app}: connected, version {version}")
                live = bazarr_client.settings()
                allowed = set(app_schema("bazarr")["config"]["settings"])
                normalised = {item.split(".", 1)[0] for item in allowed}
                for section in live:
                    if section not in normalised:
                        problems.append(f"{app}: unknown live section {section!r}")
                flat = flatten_dict(live)
                for key in flat:
                    if key not in allowed and key.split(".", 1)[0] not in normalised:
                        problems.append(f"{app}: unknown live setting {key!r}")
            except ArrctlError as exc:
                problems.append(str(exc))
            finally:
                bazarr_client.close()
            continue

        api_version = str(app_schema(app)["api_version"])
        servarr_client = ServarrClient(app, connection, api_version)
        try:
            status = servarr_client.status()
            version = status.get("version", "unknown")
            messages.append(f"{app}: connected, version {version}")
            for resource in app_schema(app)["config"]:
                try:
                    live = servarr_client.get(f"config/{resource}")
                except ApiError as exc:
                    if exc.status_code == 404:
                        continue
                    problems.append(str(exc))
                    continue
                if not isinstance(live, dict):
                    continue
                expected = config_fields(app, resource)
                actual = set(live) - {"id"}
                for key in sorted(actual - expected):
                    problems.append(
                        f"{app}.config.{resource}: live field {key!r} missing from schema"
                    )
                for key in sorted(expected - actual):
                    problems.append(
                        f"{app}.config.{resource}: schema field {key!r} not returned by live app"
                    )
            for name, definition in _resource_defs(app):
                try:
                    items = servarr_client.get(definition.path)
                except ApiError as exc:
                    if exc.status_code == 404:
                        continue
                    problems.append(str(exc))
                    continue
                if not isinstance(items, list):
                    continue
                messages.append(f"{app}.resources.{name}: {len(items)} item(s)")
        except ArrctlError as exc:
            problems.append(str(exc))
        finally:
            servarr_client.close()
    return messages, problems


def _resource_defs(app: str):
    from .resources import RESOURCES

    return RESOURCES.get(app, {}).items()
