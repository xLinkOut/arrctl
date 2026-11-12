"""Pull live configuration into a YAML document."""

from __future__ import annotations

import copy
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .client import BazarrClient, ServarrClient
from .config import Document, OnlyFilter
from .refs import resolve_refs_out
from .resources import PULL_EXCLUDE
from .schema import app_schema, config_fields, is_secret
from .util import SECRET_RE


class Puller:
    def __init__(
        self,
        document: Document,
        *,
        only: str | None = None,
        include_secrets: bool = False,
        infer_defaults: bool = False,
    ):
        self.document = document
        self.filter = OnlyFilter(only)
        self.include_secrets = include_secrets
        self.infer_defaults = infer_defaults
        self.warnings: list[str] = []
        self._ref_cache: dict[str, list[Any]] = {}

    def pull(self) -> list[str]:
        for app in list(self.document.apps):
            if not self.filter.app(app):
                continue
            if app == "bazarr":
                self._pull_bazarr(app)
            else:
                self._pull_servarr(app)
        if self.infer_defaults:
            self._infer_defaults()
        return self.warnings

    # ------------------------------------------------------------- Servarr
    def _pull_servarr(self, app: str) -> None:
        connection = self.document.connection(app)
        api_version = str(app_schema(app)["api_version"])
        client = ServarrClient(app, connection, api_version)
        app_doc = self.document.app_doc(app)
        try:
            status = client.status()
            if status.get("version"):
                app_doc["version"] = status["version"]

            config = app_doc.get("config")
            if not isinstance(config, CommentedMap):
                config = CommentedMap()
                app_doc["config"] = config
            for resource in app_schema(app)["config"]:
                if not self.filter.config(app, resource):
                    continue
                try:
                    live = client.get(f"config/{resource}")
                except Exception as exc:
                    if getattr(exc, "status_code", None) == 404:
                        continue
                    self.warnings.append(f"{app}.config.{resource}: {exc}")
                    continue
                if not isinstance(live, dict):
                    continue
                cleaned = self._clean_config(app, resource, live)
                config[resource] = self._map(cleaned)

            resources = app_doc.get("resources")
            if not isinstance(resources, CommentedMap):
                resources = CommentedMap()
                app_doc["resources"] = resources
            for name, definition in self._resource_defs(app):
                if not self.filter.resource(app, name):
                    continue
                try:
                    live = client.get(definition.path)
                except Exception as exc:
                    if getattr(exc, "status_code", None) == 404:
                        continue
                    self.warnings.append(f"{app}.resources.{name}: {exc}")
                    continue
                if not isinstance(live, list):
                    continue
                items: list[Any] = []
                for item in live:
                    if isinstance(item, dict):
                        cleaned = self._clean_resource(name, item)
                        cleaned = resolve_refs_out(client, cleaned, self._ref_cache)
                        items.append(self._map(cleaned))
                resources[name] = CommentedSeq(items)
        finally:
            client.close()

    def _pull_bazarr(self, app: str) -> None:
        connection = self.document.connection(app)
        client = BazarrClient(connection)
        app_doc = self.document.app_doc(app)
        try:
            live = client.settings()
            status = client.get("/api/system/status")
            if isinstance(status, dict) and status.get("bazarr_version"):
                app_doc["version"] = status["bazarr_version"]
            config = app_doc.get("config")
            if not isinstance(config, CommentedMap):
                config = CommentedMap()
                app_doc["config"] = config
            # Pull only sections requested via --only, otherwise everything.
            cleaned = self._clean_bazarr(live)
            if self.filter.tokens:
                for section in list(cleaned):
                    if not self.filter.config(app, section):
                        cleaned.pop(section, None)
            for section, values in cleaned.items():
                if isinstance(values, dict):
                    config[section] = self._map(values)
        finally:
            client.close()

    # ------------------------------------------------------------- cleaning
    def _clean_config(self, app: str, resource: str, live: dict[str, Any]) -> dict[str, Any]:
        fields = config_fields(app, resource)
        cleaned: dict[str, Any] = {}
        for key, value in live.items():
            if key == "id":
                continue
            if key not in fields:
                self.warnings.append(f"{app}.config.{resource}.{key}: not in bundled schema")
                continue
            if is_secret(app, resource, key) and not self.include_secrets:
                continue
            cleaned[key] = copy.deepcopy(value)
        return cleaned

    def _clean_resource(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in item.items():
            if key in PULL_EXCLUDE:
                continue
            if key == "fields" and isinstance(value, list):
                cleaned["fields"] = self._clean_fields(value)
                continue
            if not self.include_secrets and self._url_has_secret(value):
                continue
            cleaned[key] = copy.deepcopy(value)

        if name == "rootfolder":
            cleaned = {"path": item.get("path")}
        elif name == "tag":
            cleaned = {"label": item.get("label")}
        elif name == "qualitydefinition":
            quality: dict[str, Any] = (
                item["quality"] if isinstance(item.get("quality"), dict) else {}
            )
            cleaned = {
                "quality": {"name": quality.get("name")},
                "minSize": item.get("minSize"),
                "maxSize": item.get("maxSize"),
                "preferredSize": item.get("preferredSize"),
            }
        return cleaned

    def _clean_fields(self, fields: list[Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for entry in fields:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            if self._field_is_secret(str(name)) and not self.include_secrets:
                continue
            value = entry.get("value")
            if not self.include_secrets and self._url_has_secret(value):
                continue
            result[str(name)] = copy.deepcopy(value)
        return result

    @staticmethod
    def _field_is_secret(name: str) -> bool:
        return bool(SECRET_RE.search(name.rsplit(".", 1)[-1]))

    @staticmethod
    def _url_has_secret(value: Any) -> bool:
        if not isinstance(value, str) or "://" not in value:
            return False
        authority = value.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority:
            return True
        lowered = value.lower()
        return any(
            marker in lowered
            for marker in ("token=", "apikey=", "api_key=", "password=", "secret=")
        )

    # --------------------------------------------------------------- helpers
    def _clean_bazarr(self, live: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for section, values in live.items():
            if not isinstance(values, dict):
                continue
            if section == "notifications" and not self.include_secrets:
                self.warnings.append(
                    "bazarr.notifications: skipped because provider URLs may contain secrets"
                )
                continue
            section_clean: dict[str, Any] = {}
            for key, value in values.items():
                full = f"{section}.{key}"
                secret = self._field_is_secret(key) or self._field_is_secret(full)
                if secret and not self.include_secrets:
                    continue
                if not self.include_secrets and self._url_has_secret(value):
                    continue
                section_clean[key] = copy.deepcopy(value)
            cleaned[section] = section_clean
        return cleaned

    def _infer_defaults(self) -> None:
        defaults = self.document.raw.get("defaults")
        if not isinstance(defaults, CommentedMap):
            defaults = CommentedMap()
            if "defaults" in self.document.raw:
                self.document.raw["defaults"] = defaults
            else:
                position = 1 if "version" in self.document.raw else 0
                self.document.raw.insert(position, "defaults", defaults)
        apps = self.document.apps
        # Only infer for config singletons and only fields that every app
        # using that resource has with the same value.
        resource_apps: dict[str, list[str]] = {}
        for app in apps:
            if app == "bazarr":
                continue
            for resource in self.document.merged_config(app):
                resource_apps.setdefault(resource, []).append(app)
        for resource, app_names in resource_apps.items():
            if len(app_names) < 2:
                continue
            values: dict[str, dict[str, Any]] = {}
            for app in app_names:
                cfg = apps[app].get("config", {})
                if isinstance(cfg, dict) and isinstance(cfg.get(resource), dict):
                    values[app] = dict(cfg[resource])
            if len(values) < 2:
                continue
            common_keys = set.intersection(*(set(v) for v in values.values()))
            defaults_resource = defaults.get(resource)
            if not isinstance(defaults_resource, CommentedMap):
                defaults_resource = CommentedMap()
                defaults[resource] = defaults_resource
            for key in sorted(common_keys):
                if is_secret(app_names[0], resource, key):
                    continue
                first = values[app_names[0]].get(key)
                if all(values[app].get(key) == first for app in app_names if app in values):
                    defaults_resource[key] = copy.deepcopy(first)
                    for app in values:
                        values[app].pop(key, None)
                        apps[app]["config"][resource] = self._map(values[app])

    def _should_pull_all(self, app_doc: dict[str, Any]) -> bool:
        # A fresh template has empty resources; only pull collections when
        # explicitly requested through --only, or when no resources key exists.
        resources = app_doc.get("resources")
        if not isinstance(resources, dict):
            return True
        return not resources

    @staticmethod
    def _resource_defs(app: str):
        from .resources import RESOURCES

        return RESOURCES.get(app, {}).items()

    @staticmethod
    def _map(value: Any) -> Any:
        if isinstance(value, dict):
            mapping = CommentedMap()
            for key, item in value.items():
                mapping[key] = Puller._map(item)
            return mapping
        if isinstance(value, list):
            sequence = CommentedSeq()
            for item in value:
                sequence.append(Puller._map(item))
            return sequence
        return copy.deepcopy(value)
