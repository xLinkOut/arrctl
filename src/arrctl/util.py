"""Small helpers shared by the CLI and the engine."""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import ConfigError

ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
FILE_RE = re.compile(r"\$\{file:([^}]+)\}")

SECRET_RE = re.compile(
    r"(?:api[_-]?key|encryption[_-]?key|signing[_-]?key|password|passwd|token|"
    r"secret|passkey|private[_-]?key)$",
    re.IGNORECASE,
)


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge two mappings. Lists and scalars are replaced."""
    result: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve_value(value: Any, *, base_dir: Path | None = None) -> Any:
    """Resolve ${ENV}, ${ENV:-default} and ${file:path} placeholders."""
    if isinstance(value, Mapping):
        return {k: resolve_value(v, base_dir=base_dir) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, base_dir=base_dir) for v in value]
    if not isinstance(value, str):
        return value

    def env_replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        found = os.environ.get(name)
        if found is None:
            if default is not None:
                return default
            raise ConfigError(f"environment variable {name!r} is not set")
        return found

    def file_replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        path = Path(os.path.expanduser(raw))
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        try:
            return path.read_text().strip()
        except OSError as exc:
            raise ConfigError(f"cannot read secret file {path}: {exc}") from exc

    if "${" not in value:
        return value
    value = FILE_RE.sub(file_replace, value)
    return ENV_RE.sub(env_replace, value)


def read_api_key_file(path: str | Path) -> str:
    """Read <ApiKey> from a Servarr config.xml."""
    file_path = Path(os.path.expanduser(str(path)))
    try:
        text = file_path.read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read API key file {file_path}: {exc}") from exc
    match = re.search(r"<ApiKey>\s*([^<]+?)\s*</ApiKey>", text)
    if not match:
        raise ConfigError(f"no <ApiKey> element found in {file_path}")
    return match.group(1)


def get_path(obj: Any, dotted: str, default: Any = None) -> Any:
    """Read a dotted path from a nested mapping."""
    current = obj
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def set_path(obj: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted path in a nested mapping, creating intermediate dicts."""
    parts = dotted.split(".")
    current = obj
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def remove_path(obj: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    current: Any = obj
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def identity_value(item: Mapping[str, Any], identity: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(get_path(item, key) for key in identity)


def identity_label(value: tuple[Any, ...]) -> str:
    return " / ".join("" if part is None else str(part) for part in value)


def coerce_like(value: Any, current: Any) -> Any:
    """Coerce YAML scalars to the type returned by the API."""
    if value is None or current is None:
        return value
    if isinstance(current, bool) and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
    if isinstance(current, int) and not isinstance(current, bool) and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(current, float) and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if isinstance(current, str) and not isinstance(value, str):
        return str(value)
    return value


def flatten_dict(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested mappings. Lists stay as lists."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            result.update(flatten_dict(value, dotted))
        else:
            result[dotted] = value
    return result


def redact(value: Any, key: str = "") -> Any:
    """Redact values whose key looks like a secret or a credential URL."""
    if isinstance(value, Mapping):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if key and SECRET_RE.search(key):
        return "********"
    if isinstance(value, str) and "url" in key.lower() and "://" in value:
        authority = value.split("://", 1)[1].split("/", 1)[0]
        lowered = value.lower()
        if "@" in authority or any(
            marker in lowered
            for marker in ("token=", "apikey=", "api_key=", "password=", "secret=")
        ):
            return "********"
    return value


def format_value(value: Any, *, secret: bool = False) -> str:
    if secret:
        return "********"
    if isinstance(value, (dict, list)):
        return repr(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
