"""Command line interface for arrctl."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Document, new_template
from .doctor import run_doctor
from .engine import Change, Engine
from .errors import ArrctlError
from .puller import Puller
from .schema import app_schema, load_schema, validate_document
from .util import format_value

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Declarative configuration for Sonarr, Radarr, Lidarr, Whisparr, Prowlarr and Bazarr.",
)
console = Console()
err_console = Console(stderr=True)

APP_NAMES = ["sonarr", "radarr", "lidarr", "whisparr", "prowlarr", "bazarr"]
DEFAULT_PORTS = {
    "sonarr": 8010,
    "radarr": 8008,
    "lidarr": 8016,
    "whisparr": 8015,
    "prowlarr": 8007,
    "bazarr": 8011,
}


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"arrctl {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """arrctl manages the *arr stack from a single YAML file."""


def _load(path: Path, *, allow_unknown: bool) -> Document:
    document = Document.load(path)
    warnings = validate_document(document.raw, allow_unknown=allow_unknown)
    for warning in warnings:
        err_console.print(f"[yellow]warning:[/yellow] {warning}")
    return document


def _print_changes(changes: list[Change], *, as_json: bool = False) -> None:
    if as_json:
        payload = []
        for change in changes:
            payload.append(
                {
                    "app": change.app,
                    "scope": change.scope,
                    "resource": change.resource,
                    "identity": change.identity,
                    "action": change.action,
                    "field": change.field,
                    "old": None if change.secret else change.old,
                    "new": None if change.secret else change.new,
                    "secret": change.secret,
                    "requires_restart": change.requires_restart,
                }
            )
        console.print_json(json.dumps(payload))
        return
    if not changes:
        console.print("[green]No changes.[/green]")
        return
    table = Table(title=f"{len(changes)} change(s)", show_lines=False)
    table.add_column("App", style="cyan", no_wrap=True)
    table.add_column("Resource", style="magenta")
    table.add_column("Object")
    table.add_column("Field")
    table.add_column("Old")
    table.add_column("New")
    for change in changes:
        target = f"{change.resource}"
        if change.identity:
            target += f" [{change.identity}]"
        old = "********" if change.secret else format_value(change.old)
        new = "********" if change.secret else format_value(change.new)
        table.add_row(
            change.app,
            target,
            change.action,
            change.field or "",
            old,
            new,
        )
    console.print(table)
    if any(change.requires_restart for change in changes):
        console.print(
            "[yellow]Some host/network fields need a restart to take effect.[/yellow]"
        )


@app.command()
def validate(
    config: Path = typer.Option(..., "--config", "-c", help="Path to arr.yaml."),
    allow_unknown: bool = typer.Option(
        False, "--allow-unknown", help="Warn instead of failing on unknown fields."
    ),
) -> None:
    """Validate the YAML document without contacting any app."""
    try:
        document = Document.load(config)
        warnings = validate_document(document.raw, allow_unknown=allow_unknown)
    except ArrctlError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    for warning in warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")
    console.print("[green]valid[/green]")


@app.command()
def plan(
    config: Path = typer.Option(..., "--config", "-c", help="Path to arr.yaml."),
    only: str | None = typer.Option(
        None, "--only", help="Comma-separated apps/resources, e.g. sonarr.ui,radarr."
    ),
    allow_unknown: bool = typer.Option(False, "--allow-unknown"),
    wait: float = typer.Option(0, "--wait", help="Seconds to wait for each app to be ready."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Show what would change. Exits 2 when drift is found."""
    try:
        document = _load(config, allow_unknown=allow_unknown)
        result = Engine(
            document, only=only, allow_unknown=allow_unknown, wait=wait
        ).plan()
    except ArrctlError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    for warning in result.warnings:
        err_console.print(f"[yellow]warning:[/yellow] {warning}")
    _print_changes(result.changes, as_json=json_output)
    raise typer.Exit(2 if result.changes else 0)


@app.command()
def apply(
    config: Path = typer.Option(..., "--config", "-c", help="Path to arr.yaml."),
    only: str | None = typer.Option(None, "--only"),
    allow_unknown: bool = typer.Option(False, "--allow-unknown"),
    wait: float = typer.Option(0, "--wait", help="Seconds to wait for each app to be ready."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show the plan."),
    restart: bool = typer.Option(
        False, "--restart", help="Restart apps whose host/network settings changed."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Apply the YAML document to the live apps."""
    try:
        document = _load(config, allow_unknown=allow_unknown)
        engine = Engine(document, only=only, allow_unknown=allow_unknown, wait=wait)
        planned = engine.plan()
        if dry_run:
            _print_changes(planned.changes, as_json=json_output)
            raise typer.Exit(2 if planned.changes else 0)
        if not planned.changes:
            _print_changes([], as_json=json_output)
            return
        if not yes:
            if not sys.stdin.isatty():
                err_console.print(
                    "[red]error:[/red] changes are pending; use --yes in non-interactive mode."
                )
                raise typer.Exit(1)
            _print_changes(planned.changes, as_json=json_output)
            if not typer.confirm(f"Apply {len(planned.changes)} change(s)?"):
                raise typer.Exit(1)
        result = engine.apply()
        _print_changes(result.changes, as_json=json_output)
        if restart:
            _restart_apps(document, result.changes)
        console.print("[green]Applied.[/green]")
    except ArrctlError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc


def _restart_apps(document: Document, changes: list[Change]) -> None:
    from .client import ServarrClient

    apps = {change.app for change in changes if change.requires_restart and change.app != "bazarr"}
    for app in sorted(apps):
        client = ServarrClient(
            app,
            document.connection(app),
            str(app_schema(app)["api_version"]),
        )
        try:
            client.post("system/restart", {})
            console.print(f"[cyan]{app}: restart requested[/cyan]")
        except ArrctlError as exc:
            err_console.print(f"[yellow]warning:[/yellow] {app}: {exc}")
        finally:
            client.close()


@app.command()
def pull(
    config: Path = typer.Option(..., "--config", "-c", help="Path to arr.yaml."),
    only: str | None = typer.Option(None, "--only"),
    include_secrets: bool = typer.Option(
        False, "--include-secrets", help="Write API keys/passwords to YAML (unsafe)."
    ),
    infer_defaults: bool = typer.Option(
        False, "--infer-defaults", help="Move identical values into defaults."
    ),
    allow_unknown: bool = typer.Option(False, "--allow-unknown"),
) -> None:
    """Pull live settings into the YAML file, preserving comments."""
    try:
        if config.exists():
            document = Document.load(config)
        else:
            document = Document(
                new_template(
                    APP_NAMES,
                    {app: f"http://127.0.0.1:{port}" for app, port in DEFAULT_PORTS.items()},
                ),
                config,
            )
        if allow_unknown:
            validate_document(document.raw, allow_unknown=True)
        warnings = Puller(
            document,
            only=only,
            include_secrets=include_secrets,
            infer_defaults=infer_defaults,
        ).pull()
    except ArrctlError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    for warning in warnings:
        err_console.print(f"[yellow]warning:[/yellow] {warning}")
    document.save(config)
    console.print(f"[green]Wrote[/green] {config}")


@app.command()
def init(
    output: Path = typer.Option(Path("arr.yaml"), "--output", "-o", help="Output file."),
    from_live: bool = typer.Option(
        False, "--from-live", help="Prompt for URLs/API keys and pull the live configuration."
    ),
    only: str | None = typer.Option(None, "--only", help="Only these apps."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Create a starter YAML file, optionally importing the live stack."""
    if output.exists() and not force:
        err_console.print(f"[red]error:[/red] {output} already exists; use --force")
        raise typer.Exit(1)
    urls = {app: f"http://127.0.0.1:{port}" for app, port in DEFAULT_PORTS.items()}
    document = Document(new_template(APP_NAMES, urls), output)
    if from_live:
        selected = [app for app in APP_NAMES if _app_selected(only, app)]
        for app_name in selected:
            console.print(f"[cyan]{app_name}[/cyan]")
            default_url = urls[app_name]
            url = typer.prompt("  URL", default=default_url)
            env_name = f"{app_name.upper()}_API_KEY"
            default_key = ""
            import os

            default_key = os.environ.get(env_name, "")
            api_key = typer.prompt(
                f"  API key ({env_name})",
                default=default_key,
                hide_input=True,
                show_default=False,
            )
            document.raw["apps"][app_name]["connection"]["url"] = url
            document.raw["apps"][app_name]["connection"]["api_key"] = api_key
        try:
            warnings = Puller(document, only=only, infer_defaults=True).pull()
        except ArrctlError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(1) from exc
        for warning in warnings:
            err_console.print(f"[yellow]warning:[/yellow] {warning}")
    document.save(output)
    console.print(f"[green]Wrote[/green] {output}")


def _app_selected(only: str | None, app_name: str) -> bool:
    if not only:
        return True
    return any(token.split(".", 1)[0] == app_name for token in only.split(","))


@app.command()
def doctor(
    config: Path = typer.Option(..., "--config", "-c", help="Path to arr.yaml."),
    only: str | None = typer.Option(None, "--only"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 on any warning."),
) -> None:
    """Check connectivity and compare the bundled schema with the live apps."""
    try:
        document = _load(config, allow_unknown=False)
        if only:
            document = _filtered_document(document, only)
        messages, problems = run_doctor(document)
    except ArrctlError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    for message in messages:
        console.print(f"[green]ok[/green] {message}")
    for problem in problems:
        console.print(f"[yellow]warn[/yellow] {problem}")
    if problems and strict:
        raise typer.Exit(1)


@app.command("schema")
def schema_command(
    app_name: str | None = typer.Argument(None, help="App name."),
    resource: str | None = typer.Argument(None, help="Config resource or resource collection."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show the bundled schema."""
    data = load_schema()
    if app_name is None:
        console.print_json(json.dumps(data))
        return
    if app_name not in data["apps"]:
        err_console.print(f"[red]error:[/red] unknown app {app_name!r}")
        raise typer.Exit(1)
    app_data = data["apps"][app_name]
    if resource is None:
        console.print_json(json.dumps(app_data))
        return
    config = app_data["config"]
    if resource in config:
        payload: Any = config[resource]
    else:
        from .resources import get_resource

        definition = get_resource(app_name, resource)
        if definition is None:
            err_console.print(f"[red]error:[/red] unknown resource {resource!r}")
            raise typer.Exit(1)
        payload = {
            "path": definition.path,
            "identity": list(definition.identity),
            "create": definition.create,
            "update": definition.update,
            "delete": definition.delete,
            "has_schema": definition.has_schema,
        }
    console.print_json(json.dumps(payload))


def _filtered_document(document: Document, only: str) -> Document:
    """Return a shallow copy with unselected apps removed (for doctor)."""
    from ruamel.yaml.comments import CommentedMap

    raw = CommentedMap(document.raw)
    apps = CommentedMap()
    for app_name, app_doc in document.apps.items():
        if _app_selected(only, app_name):
            apps[app_name] = app_doc
    raw["apps"] = apps
    return Document(raw, document.path)


if __name__ == "__main__":
    app()
