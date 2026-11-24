"""A Dokploy instance in memory: the procedures the target uses, the calls it made."""

from __future__ import annotations

from typing import Any
from urllib import parse

from apx_dokploy.abc import Api
from apx_dokploy.client import ApiError


class FakeDokploy:
    def __init__(self, deploy_ends: str = "done") -> None:
        self.projects: list[dict[str, Any]] = []
        self.domains: dict[str, list[dict[str, Any]]] = {}
        self.deployments: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.deploy_ends = deploy_ends
        self.keys = {"good"}
        self.members: list[dict[str, Any]] = []
        self.invitations: list[dict[str, Any]] = []

    def send(self, method: str, target: str, body: dict | None, key: str) -> Any:
        procedure = target.split("/api/")[1].split("?")[0]
        query = dict(parse.parse_qsl(target.partition("?")[2]))
        self.calls.append((method, procedure, body or query))

        if key not in self.keys:
            raise ApiError(401, "UNAUTHORIZED")

        return getattr(self, procedure.replace(".", "_"))(body or query)

    def project_all(self, _: dict) -> list:
        """What Dokploy's project.all returns: an environment's applications carry applicationId, name and applicationStatus only."""
        keep = ("applicationId", "name", "applicationStatus")

        return [
            {
                **project,
                "environments": [
                    {
                        **env,
                        "applications": [
                            {k: a[k] for k in keep} for a in env["applications"]
                        ],
                    }
                    for env in project["environments"]
                ],
            }
            for project in self.projects
        ]

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
            "isDefault": True,
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
            "appName": f"{body['appName']}-x1y2z3",
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

    def application_saveEnvironment(self, body: dict) -> bool:
        self._app(body["applicationId"])["env"] = body["env"]

        return True

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
                "errorMessage": "container exited with code 1"
                if self.deploy_ends == "error"
                else None,
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

    def environment_remove(self, body: dict) -> dict:
        for p in self.projects:
            p["environments"] = [
                e
                for e in p["environments"]
                if e["environmentId"] != body["environmentId"]
            ]

        return {}

    def project_remove(self, body: dict) -> dict:
        self.projects = [
            p for p in self.projects if p["projectId"] != body["projectId"]
        ]

        return {}

    def deployment_all(self, query: dict) -> list:
        return self.deployments.get(query["applicationId"], [])

    def deployment_readLogs(self, query: dict) -> str:
        return "panic: listen tcp :8000: bind: address already in use"

    def domain_byApplicationId(self, query: dict) -> list:
        return self.domains.get(query["applicationId"], [])

    def domain_generateDomain(self, body: dict) -> str:
        return f"{body['appName']}-1a2b3c-203-0-113-7.traefik.me"

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

    def member(
        self, email: str, role: str, projects: list[str] | None = None
    ) -> dict[str, Any]:
        n = len(self.members) + 1
        row = {
            "id": f"m{n}",
            "userId": f"u{n}",
            "role": role,
            "user": {"id": f"u{n}", "email": email},
            "accessedProjects": list(projects or []),
            "accessedEnvironments": [],
            "accessedServices": [],
            "accessedGitProviders": [],
            "accessedServers": [],
            "canCreateProjects": False,
            "canAccessToDocker": False,
        }
        self.members.append(row)

        return row

    def writes(self) -> list[tuple[str, str, Any]]:
        return [c for c in self.calls if c[0] != "GET"]

    def user_all(self, _: dict) -> list:
        return self.members

    def organization_allInvitations(self, _: dict) -> list:
        return self.invitations

    def organization_inviteMember(self, body: dict) -> dict:
        self.invitations.append(
            {
                "id": f"i{len(self.invitations) + 1}",
                "email": body["email"],
                "role": body["role"],
                "status": "pending",
            }
        )

        return {}

    def organization_removeInvitation(self, body: dict) -> dict:
        self.invitations = [
            i for i in self.invitations if i["id"] != body["invitationId"]
        ]

        return {}

    def organization_updateMemberRole(self, body: dict) -> dict:
        next(m for m in self.members if m["id"] == body["memberId"])["role"] = body[
            "role"
        ]

        return {}

    def user_remove(self, body: dict) -> bool:
        self.members = [m for m in self.members if m["userId"] != body["userId"]]

        return True

    def user_assignPermissions(self, body: dict) -> None:
        member = next(m for m in self.members if m["userId"] == body["id"])
        member.update({k: v for k, v in body.items() if k != "id"})


class FakeApi(Api):
    def __init__(self, fake: FakeDokploy, key: str = "good") -> None:
        self.fake = fake
        self.key = key

    def get(self, procedure: str, **query: Any) -> Any:
        target = f"https://dokploy.test/api/{procedure}"

        if query:
            target += "?" + parse.urlencode(query)

        return self.fake.send("GET", target, None, self.key)

    def post(self, procedure: str, body: dict[str, Any] | None = None) -> Any:
        return self.fake.send(
            "POST", f"https://dokploy.test/api/{procedure}", body or {}, self.key
        )
