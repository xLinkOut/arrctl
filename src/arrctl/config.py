"""YAML document loading, merging and connection resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .errors import ConfigError
from .schema import config_resources
from .util import deep_merge, read_api_key_file, resolve_value


@dataclass
class Connection:
    url: str
    api_key: str
    verify_ssl: bool = True
    timeout: float = 30.0


class OnlyFilter:
    """Filter apps/resources using tokens like ``sonarr`` or ``sonarr.ui``."""

    def __init__(self, raw: str | None):
        self.tokens = [item.strip() for item in (raw or "").split(",") if item.strip()]

    def app(self, app: str) -> bool:
        if not self.tokens:
            return True
        return any(token == app or token.startswith(f"{app}.") for token in self.tokens)

    def config(self, app: str, resource: str) -> bool:
        if not self.tokens:
            return True
        return any(
            token in {app, f"{app}.{resource}", f"{app}.config", f"{app}.config.{resource}"}
            for token in self.tokens
        )

    def resource(self, app: str, resource: str) -> bool:
        if not self.tokens:
            return True
        return any(
            token in {app, f"{app}.{resource}", f"{app}.resources", f"{app}.resources.{resource}"}
            for token in self.tokens
        )


class Document:
    def __init__(self, raw: CommentedMap, path: Path | None = None):
        self.raw = raw
        self.path = path

    @classmethod
    def load(cls, path: Path) -> Document:
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        yaml = YAML(typ="rt")
        try:
            raw = yaml.load(path.read_text())
        except Exception as exc:
            raise ConfigError(f"cannot parse {path}: {exc}") from exc
        if not isinstance(raw, CommentedMap):
            raise ConfigError("the document must be a YAML mapping")
        return cls(raw, path)

    @property
    def apps(self) -> CommentedMap:
        apps = self.raw.get("apps")
        if not isinstance(apps, CommentedMap):
            raise ConfigError("'apps' must be a mapping")
        return apps

    @property
    def defaults(self) -> dict[str, Any]:
        defaults = self.raw.get("defaults", {})
        if not isinstance(defaults, dict):
            raise ConfigError("'defaults' must be a mapping")
        return dict(defaults)

    def app_doc(self, app: str) -> CommentedMap:
        app_doc = self.apps.get(app)
        if not isinstance(app_doc, CommentedMap):
            raise ConfigError(f"apps.{app} must be a mapping")
        return app_doc

    def merged_config(self, app: str) -> dict[str, Any]:
        app_doc = self.app_doc(app)
        explicit = app_doc.get("config", {})
        if explicit is None:
            explicit = {}
        if not isinstance(explicit, dict):
            raise ConfigError(f"apps.{app}.config must be a mapping")
        if app == "bazarr":
            # Bazarr settings are top-level sections (general, auth, ...), not
            # Servarr-style /config singletons. The Servarr defaults do not
            # apply to it.
            return deep_merge({}, explicit)
        supported = set(config_resources(app))
        for resource in explicit:
            if resource not in supported:
                raise ConfigError(
                    f"{app}: config resource {resource!r} is not supported by this app"
                )
        merged = deep_merge(self.defaults, explicit)
        # Defaults may contain resources an app does not have (for example
        # Prowlarr has no mediamanagement). Only keep what the app supports.
        return {resource: values for resource, values in merged.items() if resource in supported}

    def connection(self, app: str, *, base_dir: Path | None = None) -> Connection:
        app_doc = self.app_doc(app)
        raw = app_doc.get("connection")
        if not isinstance(raw, dict):
            raise ConfigError(f"apps.{app}.connection must be a mapping")
        resolved = resolve_value(
            raw, base_dir=base_dir or (self.path.parent if self.path else None)
        )
        url = resolved.get("url")
        if not url:
            raise ConfigError(f"apps.{app}.connection.url is required")
        api_key = resolved.get("api_key")
        if not api_key and resolved.get("api_key_file"):
            api_key = read_api_key_file(resolved["api_key_file"])
        if not api_key:
            raise ConfigError(
                f"apps.{app}.connection.api_key or api_key_file is required"
            )
        verify_ssl = resolved.get("verify_ssl", True)
        timeout = float(resolved.get("timeout", 30))
        return Connection(
            url=str(url).rstrip("/"),
            api_key=str(api_key),
            verify_ssl=bool(verify_ssl),
            timeout=timeout,
        )

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ConfigError("no output path set")
        yaml = YAML()
        yaml.default_flow_style = False
        yaml.sort_keys = False
        yaml.allow_unicode = True
        yaml.width = 4096
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as stream:
            yaml.dump(self.raw, stream)
        return target


def new_template(app_names: list[str], urls: dict[str, str] | None = None) -> CommentedMap:
    urls = urls or {}
    defaults = CommentedMap()
    defaults["host"] = CommentedMap(
        [
            ("logLevel", "info"),
            ("updateMechanism", "docker"),
            ("backupInterval", 7),
            ("backupRetention", 28),
        ]
    )
    defaults["ui"] = CommentedMap(
        [
            ("firstDayOfWeek", 1),
            ("theme", "auto"),
            ("showRelativeDates", True),
            ("uiLanguage", 1),
        ]
    )
    defaults["mediamanagement"] = CommentedMap(
        [
            ("copyUsingHardlinks", True),
            ("setPermissionsLinux", True),
            ("chmodFolder", "775"),
            ("chownGroup", "media"),
            ("importExtraFiles", True),
            ("extraFileExtensions", "srt"),
        ]
    )
    defaults["indexer"] = CommentedMap(
        [
            ("minimumAge", 0),
            ("retention", 0),
            ("maximumSize", 0),
            ("rssSyncInterval", 15),
        ]
    )

    apps = CommentedMap()
    for app in app_names:
        entry = CommentedMap()
        entry["connection"] = CommentedMap(
            [
                ("url", urls.get(app, "http://127.0.0.1:8008")),
                ("api_key", "${" + app.upper() + "_API_KEY}"),
            ]
        )
        entry["config"] = CommentedMap()
        entry["resources"] = CommentedMap()
        apps[app] = entry

    raw = CommentedMap()
    raw["version"] = 1
    raw["defaults"] = defaults
    raw["apps"] = apps
    return raw
