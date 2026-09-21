"""A Dokploy instance in memory: the procedures the target uses, the calls it made."""

from __future__ import annotations

from typing import Any
from urllib import parse

from apx_dokploy.client import ApiError


class FakeDokploy:
    def __init__(self, deploy_ends: str = "done") -> None:
        self.projects: list[dict[str, Any]] = []
        self.domains: dict[str, list[dict[str, Any]]] = {}
        self.deployments: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.deploy_ends = deploy_ends
        self.keys = {"good"}

    def send(self, method: str, target: str, body: dict | None, key: str) -> Any:
        procedure = target.split("/api/")[1].split("?")[0]
        query = dict(parse.parse_qsl(target.partition("?")[2]))
        self.calls.append((method, procedure, body or query))

        if key not in self.keys:
            raise ApiError(401, "UNAUTHORIZED")

        return getattr(self, procedure.replace(".", "_"))(body or query)

    def project_all(self, _: dict) -> list:
        return self.projects

    def project_create(self, body: dict) -> dict:
        project = {
            "projectId": f"p{len(self.projects) + 1}",
            "name": body["name"],
            "environments": [],
        }
        self.projects.append(project)
        production = {
            "environmentId": f"{project['projectId']}-production",
            "name": "production",
            "applications": [],
        }
        project["environments"].append(production)

        return project

    def environment_create(self, body: dict) -> dict:
        project = next(p for p in self.projects if p["projectId"] == body["projectId"])
        env = {
            "environmentId": f"{project['projectId']}-{body['name']}",
            "name": body["name"],
            "applications": [],
        }
        project["environments"].append(env)

        return env

    def application_create(self, body: dict) -> dict:
        env = self._env(body["environmentId"])
        app = {
            "applicationId": f"a{body['appName']}",
            "name": body["name"],
            "appName": body["appName"],
            "applicationStatus": "idle",
            "dockerImage": None,
        }
        env["applications"].append(app)

        return app

    def application_one(self, query: dict) -> dict:
        return self._app(query["applicationId"])

    def application_saveDockerProvider(self, body: dict) -> dict:
        app = self._app(body["applicationId"])
        app["dockerImage"] = body["dockerImage"]

        return app

    def application_deploy(self, body: dict) -> dict:
        app = self._app(body["applicationId"])
        app["applicationStatus"] = self.deploy_ends
        self.deployments.setdefault(app["applicationId"], []).insert(
            0,
            {
                "deploymentId": f"d{len(self.deployments.get(app['applicationId'], [])) + 1}",
                "title": body.get("title"),
                "status": self.deploy_ends,
                "createdAt": "now",
            },
        )

        return {}

    def application_delete(self, body: dict) -> dict:
        for p in self.projects:
            for e in p["environments"]:
                e["applications"] = [
                    a
                    for a in e["applications"]
                    if a["applicationId"] != body["applicationId"]
                ]

        return {}

    def deployment_all(self, query: dict) -> list:
        return self.deployments.get(query["applicationId"], [])

    def domain_byApplicationId(self, query: dict) -> list:
        return self.domains.get(query["applicationId"], [])

    def domain_create(self, body: dict) -> dict:
        self.domains.setdefault(body["applicationId"], []).append(body)

        return body

    def _env(self, environment_id: str) -> dict:
        for p in self.projects:
            for e in p["environments"]:
                if e["environmentId"] == environment_id:
                    return e

        raise ApiError(404, "environment not found")

    def _app(self, application_id: str) -> dict:
        for p in self.projects:
            for e in p["environments"]:
                for a in e["applications"]:
                    if a["applicationId"] == application_id:
                        return a

        raise ApiError(404, "application not found")
