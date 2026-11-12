"""Plan and apply engine."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from .client import BazarrClient, ServarrClient
from .config import Document, OnlyFilter
from .errors import ConfigError
from .refs import resolve_refs_in
from .resources import (
    APP_LABELS,
    CONFIG_ORDER,
    READ_ONLY_FIELDS,
    RESOURCE_PRIORITY,
    RESTART_FIELDS,
    ResourceDef,
    get_resource,
)
from .schema import config_fields, is_secret
from .util import (
    SECRET_RE,
    coerce_like,
    flatten_dict,
    format_value,
    identity_label,
    identity_value,
    resolve_value,
)


@dataclass
class Change:
    app: str
    scope: str
    resource: str
    identity: str
    action: str
    field: str | None = None
    old: Any = None
    new: Any = None
    requires_restart: bool = False
    secret: bool = False

    def describe(self) -> str:
        target = f"{APP_LABELS.get(self.app, self.app)} / {self.resource}"
        if self.identity:
            target += f" [{self.identity}]"
        if self.action == "create":
            return f"+ {target}"
        if self.action == "delete":
            return f"- {target}"
        if self.field:
            if self.secret:
                return f"~ {target}.{self.field}: ******** -> ********"
            return (
                f"~ {target}.{self.field}: "
                f"{format_value(self.old)} -> {format_value(self.new)}"
            )
        return f"~ {target}"


@dataclass
class ScanResult:
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        document: Document,
        *,
        only: str | None = None,
        allow_unknown: bool = False,
        wait: float = 0,
        include_secrets: bool = False,
    ):
        self.document = document
        self.filter = OnlyFilter(only)
        self.allow_unknown = allow_unknown
        self.wait = wait
        self.include_secrets = include_secrets
        self._ref_cache: dict[str, list[Any]] = {}

    # ------------------------------------------------------------------ plan
    def plan(self) -> ScanResult:
        return self._scan(apply=False, wait=self.wait)

    def apply(self) -> ScanResult:
        return self._scan(apply=True, wait=self.wait)

    # ------------------------------------------------------------------ scan
    def _scan(self, *, apply: bool, wait: float = 0) -> ScanResult:
        result = ScanResult()
        for app in self.document.apps:
            if not self.filter.app(app):
                continue
            if app == "bazarr":
                self._scan_bazarr(result, apply=apply, wait=wait)
            else:
                self._scan_servarr(app, result, apply=apply, wait=wait)
        return result

    def _scan_servarr(
        self,
        app: str,
        result: ScanResult,
        *,
        apply: bool,
        wait: float,
    ) -> None:
        connection = self.document.connection(app)
        api_version = self._api_version(app)
        client = ServarrClient(app, connection, api_version)
        try:
            if wait:
                client.wait_ready(wait)
            merged = self.document.merged_config(app)
            # Host last: it can change the endpoint or require a restart.
            resources = [r for r in CONFIG_ORDER if r in merged]
            for resource in resources:
                if not self.filter.config(app, resource):
                    continue
                desired = merged[resource]
                if not isinstance(desired, dict) or not desired:
                    continue
                self._scan_config(app, resource, desired, client, result, apply=apply)
            self._scan_resource_collections(app, client, result, apply=apply)
        finally:
            client.close()

    def _scan_config(
        self,
        app: str,
        resource: str,
        desired: dict[str, Any],
        client: ServarrClient,
        result: ScanResult,
        *,
        apply: bool,
    ) -> None:
        current = client.get(f"config/{resource}")
        if not isinstance(current, dict):
            raise ConfigError(f"{app}: config/{resource} did not return an object")
        changes: list[Change] = []
        payload = copy.deepcopy(current)
        for key, value in desired.items():
            if key == "id":
                continue
            if key not in config_fields(app, resource):
                message = f"{app}.config.{resource}.{key}: unknown field"
                if self.allow_unknown:
                    result.warnings.append(message)
                else:
                    raise ConfigError(message)
            old = current.get(key)
            new = coerce_like(value, old)
            if old != new:
                changes.append(
                    Change(
                        app=app,
                        scope="config",
                        resource=resource,
                        identity="",
                        action="update",
                        field=key,
                        old=old,
                        new=new,
                        requires_restart=key in RESTART_FIELDS,
                        secret=is_secret(app, resource, key),
                    )
                )
            payload[key] = new
        result.changes.extend(changes)
        if apply and changes:
            client.put(f"config/{resource}/{current.get('id', 1)}", payload)
            if resource == "host" and "apiKey" in desired:
                client.api_key = str(desired["apiKey"])

    def _scan_resource_collections(
        self,
        app: str,
        client: ServarrClient,
        result: ScanResult,
        *,
        apply: bool,
    ) -> None:
        app_doc = self.document.app_doc(app)
        resources = app_doc.get("resources", {})
        if resources is None:
            return
        if not isinstance(resources, dict):
            raise ConfigError(f"apps.{app}.resources must be a mapping")
        ordered = sorted(
            resources.items(),
            key=lambda entry: (
                RESOURCE_PRIORITY.index(entry[0]) if entry[0] in RESOURCE_PRIORITY else 999,
                entry[0],
            ),
        )
        for name, items in ordered:
            if not self.filter.resource(app, name):
                continue
            definition = get_resource(app, name)
            if definition is None:
                message = f"{app}: unknown resource collection {name!r}"
                if self.allow_unknown:
                    result.warnings.append(message)
                    continue
                raise ConfigError(message)
            if not isinstance(items, list):
                raise ConfigError(f"apps.{app}.resources.{name} must be a list")
            if not items:
                continue
            current_items = client.get(definition.path)
            if not isinstance(current_items, list):
                raise ConfigError(f"{app}: {definition.path} did not return a list")
            current_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
            for item in current_items:
                if isinstance(item, dict):
                    current_by_identity[identity_value(item, definition.identity)] = item
            for desired in items:
                if not isinstance(desired, dict):
                    raise ConfigError(f"apps.{app}.resources.{name} entries must be mappings")
                desired = resolve_value(
                    desired,
                    base_dir=self.document.path.parent if self.document.path else None,
                )
                desired = resolve_refs_in(
                    client, desired, self._ref_cache, strict=apply
                )
                ident = identity_label(identity_value(desired, definition.identity))
                current = current_by_identity.get(identity_value(desired, definition.identity))
                if current is None:
                    if not definition.create:
                        raise ConfigError(
                            f"{app}.resources.{name}: cannot create a new {name} "
                            "(this resource is read-only or predefined)"
                        )
                    if apply:
                        created = self._create_resource(client, definition, desired)
                        if isinstance(created, dict):
                            current_by_identity[
                                identity_value(created, definition.identity)
                            ] = created
                        self._ref_cache.clear()
                    result.changes.append(
                        Change(
                            app=app,
                            scope="resources",
                            resource=name,
                            identity=ident,
                            action="create",
                            new=desired,
                        )
                    )
                    continue
                changes = self._resource_field_changes(
                    app, name, definition, current, desired, result
                )
                result.changes.extend(changes)
                if apply and changes:
                    self._update_resource(client, definition, current, desired)
                    self._ref_cache.clear()
                    if definition.prepare == "quality_definition":
                        current_by_identity[identity_value(desired, definition.identity)] = desired

    def _resource_field_changes(
        self,
        app: str,
        name: str,
        definition: ResourceDef,
        current: dict[str, Any],
        desired: dict[str, Any],
        result: ScanResult,
    ) -> list[Change]:
        changes: list[Change] = []
        if definition.update is False:
            return changes
        desired_fields = desired.get("fields")
        current_fields = self._fields_to_dict(current)
        for key, value in desired.items():
            if key in {"id", "fields"}:
                continue
            old = current.get(key)
            new = coerce_like(value, old)
            if definition.prepare == "quality_definition" and key == "quality":
                old_name = old.get("name") if isinstance(old, dict) else None
                new_name = new.get("name") if isinstance(new, dict) else None
                if old_name == new_name:
                    continue
            if old != new:
                changes.append(
                    Change(
                        app=app,
                        scope="resources",
                        resource=name,
                        identity=identity_label(identity_value(desired, definition.identity)),
                        action="update",
                        field=key,
                        old=old,
                        new=new,
                        secret=self._field_is_secret(key),
                    )
                )
        if isinstance(desired_fields, dict):
            for key, value in desired_fields.items():
                old = current_fields.get(key)
                new = coerce_like(value, old)
                if old != new:
                    changes.append(
                        Change(
                            app=app,
                            scope="resources",
                            resource=name,
                            identity=identity_label(identity_value(desired, definition.identity)),
                            action="update",
                            field=f"fields.{key}",
                            old=old,
                            new=new,
                            secret=self._field_is_secret(key),
                        )
                    )
        elif desired_fields is not None:
            old = current.get("fields")
            if old != desired_fields:
                changes.append(
                    Change(
                        app=app,
                        scope="resources",
                        resource=name,
                        identity=identity_label(identity_value(desired, definition.identity)),
                        action="update",
                        field="fields",
                        old=old,
                        new=desired_fields,
                    )
                )
        return changes

    # -------------------------------------------------------------- apply ops
    def _create_resource(
        self, client: ServarrClient, definition: ResourceDef, item: dict[str, Any]
    ) -> dict[str, Any]:
        payload = copy.deepcopy(item)
        payload.pop("id", None)
        if isinstance(payload.get("fields"), dict):
            payload["fields"] = self._build_fields(client, definition, payload, current=None)
        for key in list(payload):
            if key in READ_ONLY_FIELDS or key.startswith("supportsOn"):
                payload.pop(key, None)
        if definition.prepare == "quality_definition":
            raise ConfigError("qualitydefinition cannot be created")
        return client.post(definition.path, payload)

    def _update_resource(
        self,
        client: ServarrClient,
        definition: ResourceDef,
        current: dict[str, Any],
        item: dict[str, Any],
    ) -> dict[str, Any]:
        payload = copy.deepcopy(current)
        for key, value in item.items():
            if key in {"id", "fields"}:
                continue
            payload[key] = coerce_like(value, current.get(key))
        if isinstance(item.get("fields"), dict):
            payload["fields"] = self._build_fields(client, definition, item, current=current)
        elif "fields" in item:
            payload["fields"] = copy.deepcopy(item["fields"])
        if definition.prepare == "quality_definition":
            payload = self._map_quality(client, payload)
        return client.put(f"{definition.path}/{current.get('id')}", payload)

    def _build_fields(
        self,
        client: ServarrClient,
        definition: ResourceDef,
        item: dict[str, Any],
        *,
        current: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        values = item.get("fields")
        if not isinstance(values, dict):
            raise ConfigError(f"{definition.name}: 'fields' must be a mapping")
        if current is not None and isinstance(current.get("fields"), list):
            template = copy.deepcopy(current["fields"])
        else:
            template = self._schema_fields(client, definition, item)
        by_name = {entry.get("name"): entry for entry in template if isinstance(entry, dict)}
        for key, value in values.items():
            if key in by_name:
                entry = by_name[key]
                entry["value"] = self._coerce_field_value(value, entry)
            else:
                template.append({"name": key, "value": value})
        return template

    def _schema_fields(
        self, client: ServarrClient, definition: ResourceDef, item: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not definition.has_schema:
            raise ConfigError(
                f"{definition.name}: cannot build fields without an existing resource"
            )
        schemas = client.get(f"{definition.path}/schema")
        if not isinstance(schemas, list):
            raise ConfigError(f"{definition.name}: schema endpoint did not return a list")
        impl = item.get("implementation")
        contract = item.get("configContract")
        candidates = [
            candidate
            for candidate in schemas
            if isinstance(candidate, dict)
            and (impl is None or candidate.get("implementation") == impl)
            and (contract is None or candidate.get("configContract") == contract)
        ]
        if not candidates:
            raise ConfigError(
                f"{definition.name}: no schema found for implementation={impl!r} "
                f"configContract={contract!r}"
            )
        fields = candidates[0].get("fields")
        if not isinstance(fields, list):
            raise ConfigError(f"{definition.name}: schema has no fields")
        return copy.deepcopy(fields)

    def _map_quality(
        self, client: ServarrClient, payload: dict[str, Any]
    ) -> dict[str, Any]:
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            return payload
        name = quality.get("name")
        if not name:
            return payload
        current = client.get("qualitydefinition")
        for item in current if isinstance(current, list) else []:
            if isinstance(item, dict) and item.get("quality", {}).get("name") == name:
                payload["quality"] = copy.deepcopy(item["quality"])
                return payload
        raise ConfigError(f"qualitydefinition: quality {name!r} not found on this instance")

    @staticmethod
    def _coerce_field_value(value: Any, entry: dict[str, Any]) -> Any:
        field_type = entry.get("type")
        if field_type == "checkbox" and isinstance(value, str):
            return value.lower() in {"true", "yes", "1", "on"}
        if field_type == "number" and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value
        return value

    @staticmethod
    def _fields_to_dict(item: dict[str, Any]) -> dict[str, Any]:
        fields = item.get("fields")
        if not isinstance(fields, list):
            return {}
        return {
            str(entry["name"]): entry.get("value")
            for entry in fields
            if isinstance(entry, dict) and entry.get("name")
        }

    @staticmethod
    def _field_is_secret(key: str) -> bool:
        return bool(SECRET_RE.search(key.rsplit(".", 1)[-1]))

    # --------------------------------------------------------------- bazarr
    def _scan_bazarr(self, result: ScanResult, *, apply: bool, wait: float) -> None:
        connection = self.document.connection("bazarr")
        client = BazarrClient(connection)
        try:
            if wait:
                client.wait_ready(wait)
            desired = self.document.merged_config("bazarr")
            if not desired:
                return
            current = client.settings()
            current_flat = flatten_dict(current)
            desired_flat = flatten_dict(desired)
            changes: list[Change] = []
            form_items: list[tuple[str, str]] = []
            for key, value in desired_flat.items():
                old = current_flat.get(key)
                new = coerce_like(value, old)
                if old == new:
                    continue
                secret = self._field_is_secret(key)
                changes.append(
                    Change(
                        app="bazarr",
                        scope="config",
                        resource=key.split(".", 1)[0],
                        identity="",
                        action="update",
                        field=key,
                        old=old,
                        new=new,
                        secret=secret,
                    )
                )
                form_items.extend(self._bazarr_form_items(key, new))
            result.changes.extend(changes)
            if apply and form_items:
                client.save_settings(form_items)
        finally:
            client.close()

    @staticmethod
    def _bazarr_form_items(key: str, value: Any) -> list[tuple[str, str]]:
        section, _, field = key.partition(".")
        form_key = f"{section}-{field}" if field else section
        if isinstance(value, list):
            items: list[tuple[str, str]] = []
            for entry in value:
                if isinstance(entry, (dict, list)):
                    items.append((form_key, json.dumps(entry)))
                else:
                    items.append(
                        (
                            form_key,
                            str(entry).lower() if isinstance(entry, bool) else str(entry),
                        )
                    )
            return items or [(form_key, "")]
        if isinstance(value, bool):
            return [(form_key, "true" if value else "false")]
        if value is None:
            return [(form_key, "")]
        if isinstance(value, dict):
            return [(form_key, json.dumps(value))]
        return [(form_key, str(value))]

    # --------------------------------------------------------------- helpers
    def _api_version(self, app: str) -> str:
        from .schema import app_schema

        return str(app_schema(app)["api_version"])
