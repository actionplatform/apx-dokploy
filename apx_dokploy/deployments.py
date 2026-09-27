"""Running a version: the application points at the image tag, Dokploy deploys it, the target waits for the end."""

from __future__ import annotations

import time

from action_platform.core.exception import DeployError
from action_platform.logging import emit

from apx_dokploy.abc import Api, Deployments, Record
from apx_dokploy.spec import Spec

POLL = 5
WAIT = 900
FINAL = ("done", "error")
LOG_TAIL = 30


class DokployDeployments(Deployments):
    def __init__(self, api: Api) -> None:
        self.api = api

    def start(self, app: Record, spec: Spec) -> None:
        self.api.post(
            "application.saveDockerProvider",
            {
                "applicationId": app["applicationId"],
                "dockerImage": spec.reference,
                "username": spec.registry_username,
                "password": spec.registry_password,
                "registryUrl": None,
            },
        )
        emit(f"dokploy: {app['appName']} <- {spec.reference}")
        self.api.post(
            "application.deploy",
            {
                "applicationId": app["applicationId"],
                "title": f"v{spec.version}",
                "description": f"action-platform deploy of {spec.version} to {spec.stage}",
            },
        )

    def wait(self, app: Record) -> str:
        deadline = time.monotonic() + WAIT
        seen = None

        while time.monotonic() < deadline:
            current = self.api.get(
                "application.one", applicationId=app["applicationId"]
            )
            status = str(current.get("applicationStatus") or "idle")

            if status != seen:
                emit(f"dokploy: {current.get('appName')} is {status}")
                seen = status

            if status in FINAL:
                return status

            time.sleep(POLL)

        return "timeout"

    def previous_version(self, app: Record) -> str | None:
        history = (
            self.api.get("deployment.all", applicationId=app["applicationId"]) or []
        )
        current = str(app.get("dockerImage") or "").rsplit(":", 1)[-1]
        versions = [
            str(d.get("title") or "")[1:]
            for d in history
            if d.get("status") == "done" and str(d.get("title") or "").startswith("v")
        ]

        for version in versions:
            if version != current:
                return version

        return None

    def failure(self, app: Record) -> str | None:
        """`errorMessage` and the log's last lines of the newest deployment; `readLogs` is missing on older Dokploy, which then gives the error alone."""
        history = (
            self.api.get("deployment.all", applicationId=app["applicationId"]) or []
        )

        if not history:
            return None

        latest = history[0]
        lines = [str(latest.get("errorMessage") or "").strip()]

        try:
            log = self.api.get(
                "deployment.readLogs",
                deploymentId=latest["deploymentId"],
                tail=LOG_TAIL,
            )
        except DeployError:
            log = ""

        lines.append(str(log or "").strip())
        reason = "\n".join(line for line in lines if line)

        return reason or None
