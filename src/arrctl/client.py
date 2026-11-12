"""HTTP clients for Servarr apps and Bazarr."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Connection
from .errors import ApiError, ConnectionError


class BaseClient:
    def __init__(self, app: str, connection: Connection, *, header: str):
        self.app = app
        self.connection = connection
        self.header = header
        self.api_key = connection.api_key
        self.http = httpx.Client(
            base_url=connection.url,
            verify=connection.verify_ssl,
            timeout=connection.timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> BaseClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {self.header: self.api_key, "Accept": "application/json"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = self.http.request(
                method,
                path,
                headers=self._headers(),
                json=json,
                data=data,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise ConnectionError(f"{self.app}: cannot reach {self.connection.url}: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(
                self.app,
                method,
                str(response.request.url),
                response.status_code,
                response.text,
            )
        return response

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self._request("GET", path, params=params)
        if not response.content:
            return None
        return response.json()

    def post(self, path: str, payload: Any) -> Any:
        response = self._request("POST", path, json=payload)
        if not response.content:
            return None
        return response.json()

    def put(self, path: str, payload: Any) -> Any:
        response = self._request("PUT", path, json=payload)
        if not response.content:
            return None
        return response.json()

    def delete(self, path: str) -> None:
        self._request("DELETE", path)

    def wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.get("/ping")
                return
            except (ApiError, ConnectionError) as exc:
                last_error = exc
                time.sleep(1)
        raise ConnectionError(f"{self.app}: not ready after {timeout:.0f}s: {last_error}")


class ServarrClient(BaseClient):
    def __init__(self, app: str, connection: Connection, api_version: str):
        super().__init__(app, connection, header="X-Api-Key")
        self.api_version = api_version

    def api(self, path: str) -> str:
        if path.startswith("/"):
            path = path.lstrip("/")
        return f"api/{self.api_version}/{path.lstrip('/')}"

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return super().get(self.api(path), params=params)

    def post(self, path: str, payload: Any) -> Any:
        return super().post(self.api(path), payload)

    def put(self, path: str, payload: Any) -> Any:
        return super().put(self.api(path), payload)

    def delete(self, path: str) -> None:
        super().delete(self.api(path))

    def wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                super().get("ping")
                return
            except (ApiError, ConnectionError) as exc:
                last_error = exc
                time.sleep(1)
        raise ConnectionError(f"{self.app}: not ready after {timeout:.0f}s: {last_error}")

    def status(self) -> dict[str, Any]:
        return self.get("system/status")


class BazarrClient(BaseClient):
    def __init__(self, connection: Connection):
        super().__init__("bazarr", connection, header="X-API-KEY")

    def wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.get("api/system/ping")
                return
            except (ApiError, ConnectionError) as exc:
                last_error = exc
                time.sleep(1)
        raise ConnectionError(f"bazarr: not ready after {timeout:.0f}s: {last_error}")

    def settings(self) -> dict[str, Any]:
        data = self.get("api/system/settings")
        return data if isinstance(data, dict) else {}

    def save_settings(self, items: list[tuple[str, str]]) -> None:
        data: dict[str, list[str]] = {}
        for key, value in items:
            data.setdefault(key, []).append(value)
        self._request("POST", "api/system/settings", data=data)
