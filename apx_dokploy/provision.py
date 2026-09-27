"""One Dokploy project per repository, one environment per scope, one application inside it — found, or created when missing."""

from __future__ import annotations

import re

from action_platform.logging import emit

from apx_dokploy.abc import Api, Provisioner, Record
from apx_dokploy.spec import Spec


class DokployProvisioner(Provisioner):
    def __init__(self, api: Api) -> None:
        self.api = api

    def find(self, spec: Spec) -> Record | None:
        matches = self._matches(spec)

        return self._full(matches[0]) if matches else None

    def duplicates(self, spec: Spec) -> list[Record]:
        return self._matches(spec)[1:]

    def ensure(self, spec: Spec) -> Record:
        project = self._project(spec)

        if project is None:
            created = self.api.post(
                "project.create",
                {"name": spec.project, "description": "Managed by Action Platform"},
            )
            emit(f"dokploy: created project {spec.project}")
            project = self._project(spec) or created

        environment = self._environment(project, spec)

        if environment is None:
            environment = self.api.post(
                "environment.create",
                {
                    "name": spec.stage,
                    "projectId": project["projectId"],
                    "description": f"Scope {spec.stage}",
                },
            )
            emit(f"dokploy: created environment {spec.stage}")

        found = self._applications(environment, spec)
        app = self._full(found[0]) if found else None

        if app is None:
            app = self.api.post(
                "application.create",
                {
                    "name": spec.application,
                    "appName": spec.app_name,
                    "environmentId": environment["environmentId"],
                    "description": "Managed by Action Platform",
                },
            )
            emit(f"dokploy: created application {spec.app_name}")

        return app

    def remove(self, spec: Spec) -> list[str]:
        """Every application of the scope; its environment once nothing else runs there (Dokploy's default one stays); the project once none of its environments holds a service."""
        gone = []

        for app in self._matches(spec):
            self.api.post("application.delete", {"applicationId": app["applicationId"]})
            gone.append(f"application {app['applicationId']}")

        project = self._project(spec)
        environment = self._environment(project, spec) if project else None

        if environment and not environment.get("isDefault") and _empty(environment):
            self.api.post(
                "environment.remove", {"environmentId": environment["environmentId"]}
            )
            gone.append(f"environment {spec.stage}")
            project = self._project(spec)

        if project and all(_empty(e) for e in project.get("environments") or []):
            self.api.post("project.remove", {"projectId": project["projectId"]})
            gone.append(f"project {spec.project}")

        return gone

    def _project(self, spec: Spec) -> Record | None:
        for project in self.api.get("project.all") or []:
            if project.get("name") == spec.project:
                return project

        return None

    @staticmethod
    def _environment(project: Record, spec: Spec) -> Record | None:
        for environment in project.get("environments") or []:
            if environment.get("name") == spec.stage:
                return environment

        return None

    def _matches(self, spec: Spec) -> list[Record]:
        project = self._project(spec)
        environment = self._environment(project, spec) if project else None

        return self._applications(environment, spec) if environment else []

    @staticmethod
    def _applications(environment: Record, spec: Spec) -> list[Record]:
        """The environment is the scope, so the application is the one named after it. `project.all` lists applications with `applicationId`, `name` and `applicationStatus` only; `appName` — which Dokploy suffixes (`shop-prod` becomes `shop-prod-x1y2z3`) — is matched when a response carries it."""
        app_name = re.compile(rf"{re.escape(spec.app_name)}(-[a-z0-9]{{6}})?")

        return [
            app
            for app in environment.get("applications") or []
            if app.get("name") == spec.application
            or app_name.fullmatch(str(app.get("appName") or ""))
        ]

    def _full(self, found: Record | None) -> Record | None:
        if found is None:
            return None

        return self.api.get("application.one", applicationId=found["applicationId"])


SERVICES = (
    "applications",
    "compose",
    "libsql",
    "mariadb",
    "mongo",
    "mysql",
    "postgres",
    "redis",
)


def _empty(environment: Record) -> bool:
    return not any(environment.get(kind) for kind in SERVICES)
