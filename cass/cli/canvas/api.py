"""``cass canvas api`` — send a raw request to the Canvas API."""

from __future__ import annotations

__docformat__ = "google"

import json
from typing import Any

import typer

from . import _common
from ._common import canvas_app

_PARAM_OPTION = typer.Option(
    None, "--param", "-p", help="Query parameter KEY=VALUE (repeatable)"
)
_DATA_OPTION = typer.Option(
    None, "--data", "-d", help="Form field KEY=VALUE (repeatable)"
)


def _usage_error(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=2)


@canvas_app.command(name="api", rich_help_panel="Manage")
def api(
    method: str = typer.Argument(..., help="HTTP method, e.g. GET, POST, PUT, DELETE"),
    path: str = typer.Argument(
        ..., help="API path; {course} expands to the configured course ID"
    ),
    param: list[str] | None = _PARAM_OPTION,
    data: list[str] | None = _DATA_OPTION,
    json_body: str = typer.Option(
        "", "--json-body", help="Request body as a JSON string"
    ),
    all_pages: bool = typer.Option(
        False, "--all", help="Follow pagination (GET only); print one JSON array"
    ),
    dry_run: bool = _common.dry_run_option(),
) -> None:
    """Send a raw Canvas API request and print the response body."""
    import httpx

    from ...apis.canvas.auth import CanvasAuthError
    from ...apis.canvas.errors import CanvasAPIError
    from ...apis.canvas.raw import expand_course, form_content, parse_pairs

    method = method.upper()
    try:
        params = parse_pairs(param or [])
        form = parse_pairs(data or [])
    except ValueError as exc:
        raise _usage_error(str(exc)) from None
    json_value: Any = None
    if json_body:
        try:
            json_value = json.loads(json_body)
        except json.JSONDecodeError as exc:
            raise _usage_error(f"Invalid --json-body: {exc}") from None
        if form:
            raise _usage_error("Use either --data or --json-body, not both.")
    if all_pages and method != "GET":
        raise _usage_error("--all only works with GET.")

    _common.require_canvas()
    try:
        with _common.client(dry_run=dry_run) as c:
            path = expand_course(path, c.course_id)
            if all_pages:
                typer.echo(json.dumps(c.get_all(path, params=params)))
            else:
                if method != "GET":
                    typer.echo(f"{method} {c.url_for(path)}", err=True)
                    if form:
                        typer.echo(form_content(form).decode(), err=True)
                    elif json_body:
                        typer.echo(json_body, err=True)
                kwargs: dict[str, Any] = {
                    "params": params or None,
                    "data": form or None,
                }
                if json_body:
                    kwargs["json"] = json_value
                resp = c.request(method, path, **kwargs)
                if resp.content:
                    typer.echo(resp.text)
            if dry_run:
                _common.print_plan(c, err=True)
    except (CanvasAPIError, CanvasAuthError, httpx.TransportError) as exc:
        typer.echo("Error: " + " ".join(str(exc).split()), err=True)
        raise typer.Exit(code=1) from None
