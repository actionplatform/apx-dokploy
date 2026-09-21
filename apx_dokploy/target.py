"""The `dokploy` deploy target: the CI publishes `<image>:<version>`, the platform points the Dokploy application at that tag and asks it to deploy.

    [deploy]
    target = "dokploy"
    url = "https://dokploy.example.com"     # or the plugin option / AP_DOKPLOY_URL
    image = "ghcr.io/acme/shop"             # default: ghcr.io/<[source_host] repo>
    project = "shop"                        # Dokploy project; default: [project] name
    application = "shop"                    # Dokploy application; default: [project] name
    port = 8000                             # what the container listens on

    [deploy.domains]
    prod = "shop.example.com"
    dev = "shop-dev.example.com"

One Dokploy project per repository, one Dokploy environment per scope (`ctx.stage`),
one application inside it; `create` provisions what is missing. The API key never
touches platform.toml: it is the plugin's `api_key` option (`AP_DOKPLOY_API_KEY` on
a deploy job) or `DOKPLOY_API_KEY` on a machine.
"""

from __future__ import annotations

import time
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from action_platform.abc import DeployTarget
from action_platform.core.context import Check, Context, DeployResult, Diagnosis
from action_platform.core.exception import DeployError
from action_platform.logging import emit, logger

from apx_dokploy import client
from apx_dokploy.client import ApiError, Dokploy
from apx_dokploy.settings import setting

POLL = 5
WAIT = 900
FINAL = ("done", "error")


class DokployTarget(DeployTarget):
    name = "dokploy"

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        image: str | None = None,
        project: str | None = None,
        application: str | None = None,
        port: int = 8000,
        domains: dict[str, str] | None = None,
        registry_username: str | None = None,
        registry_password: str | None = None,
        **_: object,
    ) -> None:
        self.url_option = url
        self.api_key_option = api_key
        self.image_option = image
        self.project_option = project
        self.application_option = application
        self.port = int(port)
        self.domains = dict(domains or {})
        self.registry_username = registry_username
        self.registry_password = registry_password
        self._ctx: Context | None = None
        self._manifest: dict[str, Any] | None = None

    def preflight(self, ctx: Context) -> None:
        self._remember(ctx)
        blocking = [c for c in self.readiness(ctx) if c.blocking]

        if blocking:
            raise DeployError("; ".join(f"{c.id}: {c.detail}" for c in blocking))

    def readiness(self, ctx: Context) -> list[Check]:
        self._remember(ctx)
        checks = [self._check_settings(ctx)]

        if not checks[0].ok:
            return checks

        checks.append(self._check_image(ctx))
        checks.append(self._check_api(ctx))

        if checks[-1].ok:
            checks.append(self._check_application(ctx))

        return checks

    def create(self, ctx: Context) -> None:
        self._remember(ctx)
        self._ensure_application(ctx)

    def deploy(self, ctx: Context) -> DeployResult:
        self._remember(ctx)
        app = self._ensure_application(ctx)
        reference = f"{self._image(ctx)}:{ctx.next_version}"
        api = self._api(ctx)
        api.post(
            "application.saveDockerProvider",
            {
                "applicationId": app["applicationId"],
                "dockerImage": reference,
                "username": self._registry_credentials(ctx)[0],
                "password": self._registry_credentials(ctx)[1],
                "registryUrl": None,
            },
        )
        emit(f"dokploy: {app['appName']} <- {reference}")
        api.post(
            "application.deploy",
            {
                "applicationId": app["applicationId"],
                "title": f"v{ctx.next_version}",
                "description": f"action-platform deploy of {ctx.next_version} to {ctx.stage}",
            },
        )
        status = self._wait(api, app["applicationId"])
        ok = status == "done"
        logger.info(
            "dokploy: %s %s to %s",
            ctx.next_version,
            "deployed" if ok else "failed",
            ctx.stage,
        )

        return DeployResult(
            ok=ok,
            target=self.name,
            version=ctx.next_version,
            url=self._url_of(api, app),
            error=None if ok else f"dokploy deployment ended {status}",
        )

    def rollback(self, ctx: Context, to_version: str | None = None) -> None:
        self._remember(ctx)
        api = self._api(ctx)
        app = self._find_application(api, ctx)

        if app is None:
            raise DeployError(f"no dokploy application for {ctx.stage}")

        version = to_version or self._previous_version(api, app)

        if not version:
            raise DeployError(
                "no earlier version in the deployment history to go back to"
            )

        rolled = replace(ctx, next_version=version)
        result = self.deploy(rolled)

        if not result.ok:
            raise DeployError(result.error or "rollback failed")

    def diagnose(self, ctx: Context) -> Diagnosis:
        self._remember(ctx)

        try:
            api = self._api(ctx)
            app = self._find_application(api, ctx)
        except DeployError as e:
            return Diagnosis(
                ok=False,
                target=self.name,
                status="unreachable",
                details={"error": str(e)},
            )

        if app is None:
            return Diagnosis(ok=False, target=self.name, status="missing")

        status = str(app.get("applicationStatus") or "unknown")
        image = str(app.get("dockerImage") or "")

        return Diagnosis(
            ok=status == "done",
            target=self.name,
            status=status,
            version=image.rsplit(":", 1)[1] if ":" in image else None,
            url=self._url_of(api, app),
            details={
                "application": app["appName"],
                "image": image,
                "project": self._project(ctx),
                "environment": ctx.stage,
            },
        )

    def delete(self, ctx: Context) -> None:
        self._remember(ctx)
        api = self._api(ctx)
        app = self._find_application(api, ctx)

        if app is None:
            return

        api.post("application.delete", {"applicationId": app["applicationId"]})
        logger.info("dokploy: deleted %s", app["appName"])

    def verify(self, version: str, stage: str | None = None) -> bool:
        ctx = self._context(stage)
        api = self._api(ctx)
        app = self._find_application(api, ctx)

        if app is None:
            return False

        image = str(app.get("dockerImage") or "")

        return image.endswith(f":{version}") and app.get("applicationStatus") == "done"

    def url(self, version: str, stage: str | None = None) -> str | None:
        ctx = self._context(stage)

        try:
            api = self._api(ctx)
            app = self._find_application(api, ctx)
        except DeployError:
            return None

        return self._url_of(api, app) if app else None

    def _check_settings(self, ctx: Context) -> Check:
        missing = []

        if not self._base_url(ctx):
            missing.append("url ([deploy] url, the plugin's url option or DOKPLOY_URL)")

        if not self._api_key(ctx):
            missing.append("api key (the plugin's api_key option or DOKPLOY_API_KEY)")

        if not self._image(ctx):
            missing.append("image ([deploy] image or [source_host] repo)")

        return Check(
            "dokploy.settings",
            not missing,
            "url, api key and image are set"
            if not missing
            else "missing " + ", ".join(missing),
            fix=None
            if not missing
            else "set the plugin options on the platform, or DOKPLOY_URL and DOKPLOY_API_KEY on a machine",
        )

    def _check_image(self, ctx: Context) -> Check:
        reference = f"{self._image(ctx)}:{ctx.next_version}"
        username, password = self._registry_credentials(ctx)

        try:
            found = client.image_exists(
                self._image(ctx), ctx.next_version, username, password
            )
        except DeployError as e:
            return Check(
                "image.published",
                False,
                str(e),
                severity="warning",
                fix="check the registry and its credentials",
            )

        return Check(
            "image.published",
            found,
            f"{reference} is in the registry"
            if found
            else f"{reference} is not in the registry yet",
            fix=None
            if found
            else "let the image workflow finish on the release tag, then ask for readiness again",
        )

    def _check_api(self, ctx: Context) -> Check:
        try:
            self._api(ctx).get("project.all")
        except ApiError as e:
            fix = (
                "generate a key under Settings > API Keys in Dokploy and set the plugin's api_key option"
                if e.status in (401, 403)
                else None
            )

            return Check("dokploy.credentials", False, str(e), fix=fix)
        except DeployError as e:
            return Check(
                "dokploy.credentials",
                False,
                str(e),
                fix="check [deploy] url and that the instance is reachable from the worker",
            )

        return Check(
            "dokploy.credentials", True, f"{self._base_url(ctx)} accepts the key"
        )

    def _check_application(self, ctx: Context) -> Check:
        app = self._find_application(self._api(ctx), ctx)
        name = f"{self._project(ctx)}/{ctx.stage}/{self._application(ctx)}"

        if app is None:
            return Check(
                "dokploy.application",
                True,
                f"{name} does not exist yet; the deploy creates it",
                severity="warning",
            )

        status = app.get("applicationStatus")

        return Check(
            "dokploy.application",
            status != "running",
            f"{name} is {status}"
            if status != "running"
            else f"{name} is mid-deployment",
            fix=None
            if status != "running"
            else "wait for the running deployment to finish",
        )

    def _ensure_application(self, ctx: Context) -> dict[str, Any]:
        api = self._api(ctx)
        project = self._find_project(api, ctx)

        if project is None:
            project = api.post(
                "project.create",
                {
                    "name": self._project(ctx),
                    "description": "Managed by Action Platform",
                },
            )
            emit(f"dokploy: created project {self._project(ctx)}")
            project = self._find_project(api, ctx) or project

        environment = self._find_environment(project, ctx)

        if environment is None:
            environment = api.post(
                "environment.create",
                {
                    "name": ctx.stage,
                    "projectId": project["projectId"],
                    "description": f"Scope {ctx.stage}",
                },
            )
            emit(f"dokploy: created environment {ctx.stage}")

        app = self._find_in(environment, ctx)

        if app is None:
            app = api.post(
                "application.create",
                {
                    "name": self._application(ctx),
                    "appName": self._app_name(ctx),
                    "environmentId": environment["environmentId"],
                    "description": "Managed by Action Platform",
                },
            )
            emit(f"dokploy: created application {self._app_name(ctx)}")
            self._ensure_domain(api, app, ctx)

        return app

    def _ensure_domain(self, api: Dokploy, app: dict[str, Any], ctx: Context) -> None:
        host = self.domains.get(ctx.stage)

        if not host:
            return

        existing = (
            api.get("domain.byApplicationId", applicationId=app["applicationId"]) or []
        )

        if any(d.get("host") == host for d in existing):
            return

        api.post(
            "domain.create",
            {
                "host": host,
                "port": self.port,
                "https": True,
                "certificateType": "letsencrypt",
                "applicationId": app["applicationId"],
                "domainType": "application",
            },
        )
        emit(f"dokploy: domain {host} -> {app['appName']}:{self.port}")

    def _wait(self, api: Dokploy, application_id: str) -> str:
        deadline = time.monotonic() + WAIT
        seen = None

        while time.monotonic() < deadline:
            app = api.get("application.one", applicationId=application_id)
            status = str(app.get("applicationStatus") or "idle")

            if status != seen:
                emit(f"dokploy: {app.get('appName')} is {status}")
                seen = status

            if status in FINAL:
                return status

            time.sleep(POLL)

        return "timeout"

    def _previous_version(self, api: Dokploy, app: dict[str, Any]) -> str | None:
        history = api.get("deployment.all", applicationId=app["applicationId"]) or []
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

    def _find_project(self, api: Dokploy, ctx: Context) -> dict[str, Any] | None:
        wanted = self._project(ctx)

        for project in api.get("project.all") or []:
            if project.get("name") == wanted:
                return project

        return None

    def _find_environment(
        self, project: dict[str, Any], ctx: Context
    ) -> dict[str, Any] | None:
        for environment in project.get("environments") or []:
            if environment.get("name") == ctx.stage:
                return environment

        return None

    def _find_in(
        self, environment: dict[str, Any], ctx: Context
    ) -> dict[str, Any] | None:
        wanted = self._app_name(ctx)

        for app in environment.get("applications") or []:
            if app.get("appName") == wanted:
                return app

        return None

    def _find_application(self, api: Dokploy, ctx: Context) -> dict[str, Any] | None:
        project = self._find_project(api, ctx)

        if project is None:
            return None

        environment = self._find_environment(project, ctx)

        if environment is None:
            return None

        found = self._find_in(environment, ctx)

        return (
            api.get("application.one", applicationId=found["applicationId"])
            if found
            else None
        )

    def _url_of(self, api: Dokploy, app: dict[str, Any]) -> str | None:
        try:
            domains = (
                api.get("domain.byApplicationId", applicationId=app["applicationId"])
                or []
            )
        except DeployError:
            return None

        for domain in domains:
            if domain.get("host"):
                scheme = "https" if domain.get("https") else "http"

                return f"{scheme}://{domain['host']}{domain.get('path') or ''}"

        return None

    def _api(self, ctx: Context) -> Dokploy:
        url = self._base_url(ctx)
        key = self._api_key(ctx)

        if not url or not key:
            raise DeployError(
                "dokploy url or api key missing: see the dokploy.settings check"
            )

        return Dokploy(url, key)

    def _base_url(self, ctx: Context) -> str | None:
        return setting("url", self.url_option, ctx.env)

    def _api_key(self, ctx: Context) -> str | None:
        return setting("api_key", self.api_key_option, ctx.env)

    def _registry_credentials(self, ctx: Context) -> tuple[str | None, str | None]:
        return (
            setting("registry_username", self.registry_username, ctx.env),
            setting("registry_password", self.registry_password, ctx.env),
        )

    def _image(self, ctx: Context) -> str | None:
        if self.image_option:
            return self.image_option

        repo = str(self._toml(ctx).get("source_host", {}).get("repo") or "")

        return f"ghcr.io/{repo.lower()}" if repo else None

    def _project(self, ctx: Context) -> str:
        return self.project_option or self._project_name(ctx)

    def _application(self, ctx: Context) -> str:
        return self.application_option or self._project_name(ctx)

    def _app_name(self, ctx: Context) -> str:
        return f"{self._application(ctx)}-{ctx.stage}"

    def _project_name(self, ctx: Context) -> str:
        name = str(self._toml(ctx).get("project", {}).get("name") or ctx.repo_root.name)

        return name.lower().replace(" ", "-")

    def _toml(self, ctx: Context) -> dict[str, Any]:
        if self._manifest is None:
            path = ctx.repo_root / "platform.toml"
            self._manifest = tomllib.loads(path.read_text()) if path.exists() else {}

        return self._manifest

    def _remember(self, ctx: Context) -> None:
        self._ctx = ctx
        self._manifest = None

    def _context(self, stage: str | None) -> Context:
        base = self._ctx or Context(repo_root=Path.cwd())

        return replace(base, stage=stage or base.stage or "prod")
