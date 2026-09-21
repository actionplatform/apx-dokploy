"""`dokploy_*` MCP tools: read-only looks at what runs on the instance. Deploying stays with the core's `deploy` tool, which drives the target."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from action_platform.mcp.annotations import READ_ONLY
from pydantic import BaseModel, Field

from apx_dokploy.settings import connect


class Project(BaseModel):
    id: str
    name: str
    environments: list[str]


class Application(BaseModel):
    id: str
    name: str
    app_name: str
    project: str
    environment: str
    status: Optional[str] = None
    image: Optional[str] = None


class Deployment(BaseModel):
    id: str
    title: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None


def projects_of(api: Any) -> list[Project]:
    return [
        Project(
            id=p["projectId"],
            name=p["name"],
            environments=[e["name"] for e in p.get("environments") or []],
        )
        for p in api.get("project.all") or []
    ]


def applications_of(api: Any, project: str = "") -> list[Application]:
    found = []

    for p in api.get("project.all") or []:
        if project and p.get("name") != project:
            continue

        for e in p.get("environments") or []:
            for a in e.get("applications") or []:
                found.append(
                    Application(
                        id=a["applicationId"],
                        name=a["name"],
                        app_name=a["appName"],
                        project=p["name"],
                        environment=e["name"],
                        status=a.get("applicationStatus"),
                        image=a.get("dockerImage"),
                    )
                )

    return found


def deployments_of(api: Any, application_id: str, limit: int = 10) -> list[Deployment]:
    rows = api.get("deployment.all", applicationId=application_id) or []

    return [
        Deployment(
            id=d["deploymentId"],
            title=d.get("title"),
            status=d.get("status"),
            created_at=d.get("createdAt"),
        )
        for d in rows[:limit]
    ]


def register_tools(mcp: Any, options: Any) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def projects() -> list[Project]:
        """Dokploy projects and the environments each one holds — a project per repository, an environment per scope."""
        return projects_of(connect(options))

    @mcp.tool(annotations=READ_ONLY)
    def applications(
        project: Annotated[str, Field(description="Only this Dokploy project")] = "",
    ) -> list[Application]:
        """Applications on the instance with their status and the image they run."""
        return applications_of(connect(options), project)

    @mcp.tool(annotations=READ_ONLY)
    def deployments(
        application_id: Annotated[str, Field(description="The application's id")],
        limit: Annotated[int, Field(description="How many, newest first")] = 10,
    ) -> list[Deployment]:
        """The deployment history of one application — every platform deploy is titled with its version."""
        return deployments_of(connect(options), application_id, limit)
