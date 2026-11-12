"""Exceptions used by arrctl."""


class ArrctlError(Exception):
    """Base error for user-facing failures."""


class ConfigError(ArrctlError):
    """The YAML document is invalid."""


class ConnectionError(ArrctlError):
    """An app could not be reached or rejected the API key."""


class ApiError(ArrctlError):
    """An app returned a non-successful response."""

    def __init__(self, app: str, method: str, url: str, status_code: int, body: str):
        self.app = app
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"{app}: {method} {url} -> HTTP {status_code}: {body[:500]}")
