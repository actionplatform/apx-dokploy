"""`action-platform dokploy …` — the same reads as the tools, from a terminal."""

from __future__ import annotations

from typing import Any

import typer

from apx_dokploy.settings import connect
from apx_dokploy.tools import applications_of, deployments_of, projects_of

app = typer.Typer(
    help="Dokploy: projects, applications, deployments.", no_args_is_help=True
)
options: Any | None = None


@app.command("projects")
def projects() -> None:
    """List the projects and their environments."""
    for p in projects_of(connect(options)):
        typer.echo(f"{p.name}\t{', '.join(p.environments)}\t{p.id}")


@app.command("applications")
def applications(project: str = typer.Option("", help="Only this project")) -> None:
    """List the applications, their status and image."""
    for a in applications_of(connect(options), project):
        typer.echo(
            f"{a.project}/{a.environment}/{a.app_name}\t{a.status}\t{a.image or '-'}\t{a.id}"
        )


@app.command("deployments")
def deployments(application_id: str, limit: int = typer.Option(10)) -> None:
    """Deployment history of one application."""
    for d in deployments_of(connect(options), application_id, limit):
        typer.echo(f"{d.created_at}\t{d.status}\t{d.title or '-'}\t{d.id}")
