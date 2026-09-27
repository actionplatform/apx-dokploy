"""The `dokploy` deploy target: the CI publishes `<image>:<version>`, the platform points the Dokploy application at that tag and asks it to deploy.

    [deploy]
    target = "dokploy"
    url = "https://dokploy.example.com"     # or the plugin option / AP_DOKPLOY_URL
    image = "ghcr.io/acme/shop"             # default: ghcr.io/<[source_host] repo>
    project = "shop"                        # Dokploy project; default: [project] name
    application = "shop"                    # Dokploy application; default: [project] name
    port = 8000                             # what the container listens on
    health = "/health"                      # checked after the deploy; "" skips it

    [deploy.domains]                        # optional: without one, Dokploy generates
    prod = "shop.example.com"               # <app>.<server ip>.traefik.me (plain HTTP)
    dev = "shop-dev.example.com"

One Dokploy project per repository, one Dokploy environment per scope (`ctx.stage`),
one application inside it; `create` provisions what is missing. The API key never
touches platform.toml: it is the plugin's `api_key` option (`AP_DOKPLOY_API_KEY` on
a deploy job) or `DOKPLOY_API_KEY` on a machine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from action_platform.abc import DeployTarget
from action_platform.core.context import Check, Context, DeployResult, Diagnosis
from action_platform.core.exception import DeployError
from action_platform.logging import emit, logger

from apx_dokploy.abc import (
    Api,
    Deployments,
    Domains,
    Health,
    Provisioner,
    Readiness,
    Record,
    Registry,
)
from apx_dokploy.checks import ApiCheck, ApplicationCheck, ImageCheck, SettingsCheck
from apx_dokploy.client import Dokploy
from apx_dokploy.deployments import DokployDeployments
from apx_dokploy.domains import DokployDomains
from apx_dokploy.health import HttpHealth
from apx_dokploy.provision import DokployProvisioner
from apx_dokploy.registry import OciRegistry
from apx_dokploy.spec import Options, Spec


@dataclass(frozen=True)
class Parts:
    """Every responsibility wired to one instance."""

    api: Api
    provisioner: Provisioner
    domains: Domains
    deployments: Deployments


class DokployTarget(DeployTarget):
    name = "dokploy"
    registry: Registry = OciRegistry()
    health: Health = HttpHealth()

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
        health: str = "/health",
        **_: object,
    ) -> None:
        self.options = Options(
            url=url,
            api_key=api_key,
            image=image,
            project=project,
            application=application,
            port=int(port),
            domains=dict(domains or {}),
            registry_username=registry_username,
            registry_password=registry_password,
            health=health,
        )
        self._last: Context | None = None

    def spec(self, ctx: Context) -> Spec:
        self._last = ctx

        return Spec.of(ctx, self.options)

    def parts(self, spec: Spec) -> Parts:
        """The Dokploy implementation of every responsibility; override to swap one."""
        if not spec.url or not spec.api_key:
            raise DeployError(
                "dokploy url or api key missing: see the dokploy.settings check"
            )

        api = Dokploy(spec.url, spec.api_key)

        return Parts(
            api=api,
            provisioner=DokployProvisioner(api),
            domains=DokployDomains(api),
            deployments=DokployDeployments(api),
        )

    def checks(self, spec: Spec) -> list[Readiness]:
        """Settings first; the rest only once there is an instance to ask."""
        settings = SettingsCheck()

        if not settings.run(spec).ok:
            return [settings]

        parts = self.parts(spec)

        return [
            settings,
            ImageCheck(self.registry),
            ApiCheck(parts.api),
            ApplicationCheck(parts.provisioner),
        ]

    def preflight(self, ctx: Context) -> None:
        blocking = [c for c in self.readiness(ctx) if c.blocking]

        if blocking:
            raise DeployError("; ".join(f"{c.id}: {c.detail}" for c in blocking))

    def readiness(self, ctx: Context) -> list[Check]:
        spec = self.spec(ctx)
        results: list[Check] = []

        for check in self.checks(spec):
            if check.id == ApplicationCheck.id and not results[-1].ok:
                break

            results.append(check.run(spec))

        return results

    def create(self, ctx: Context) -> None:
        spec = self.spec(ctx)
        self.parts(spec).provisioner.ensure(spec)

    def deploy(self, ctx: Context) -> DeployResult:
        spec = self.spec(ctx)
        parts = self.parts(spec)
        image = ImageCheck(self.registry).run(spec)

        if image.blocking:
            raise DeployError(f"{image.detail}: {image.fix}")

        app = parts.provisioner.ensure(spec)

        for extra in parts.provisioner.duplicates(spec):
            emit(
                f"dokploy: {spec.label} also holds application {extra['applicationId']}; "
                f"deploying {app['applicationId']}, delete the other in Dokploy"
            )

        parts.domains.ensure(app, spec)
        parts.deployments.start(app, spec)
        status = parts.deployments.wait(app)
        ok = status == "done"
        reason = None if ok else parts.deployments.failure(app)
        url = parts.domains.url_of(app)

        if ok and url and spec.health:
            unhealthy = self.health.answers(url.rstrip("/") + spec.health)

            if unhealthy:
                ok, status, reason = False, "unhealthy", unhealthy

        if reason:
            emit(f"dokploy: {reason}")
        logger.info(
            "dokploy: %s %s to %s",
            spec.version,
            "deployed" if ok else "failed",
            spec.stage,
        )

        return DeployResult(
            ok=ok,
            target=self.name,
            version=spec.version,
            url=url,
            error=None
            if ok
            else f"dokploy deployment ended {status}"
            + (f": {reason.splitlines()[0]}" if reason else ""),
        )

    def rollback(self, ctx: Context, to_version: str | None = None) -> None:
        spec = self.spec(ctx)
        parts = self.parts(spec)
        app = parts.provisioner.find(spec)

        if app is None:
            raise DeployError(f"no dokploy application for {spec.stage}")

        version = to_version or parts.deployments.previous_version(app)

        if not version:
            raise DeployError(
                "no earlier version in the deployment history to go back to"
            )

        result = self.deploy(replace(ctx, next_version=version))

        if not result.ok:
            raise DeployError(result.error or "rollback failed")

    def diagnose(self, ctx: Context) -> Diagnosis:
        spec = self.spec(ctx)

        try:
            parts = self.parts(spec)
            app = parts.provisioner.find(spec)
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
            url=parts.domains.url_of(app),
            details={
                "application": app["appName"],
                "image": image,
                "project": spec.project,
                "environment": spec.stage,
            },
        )

    def delete(self, ctx: Context) -> None:
        spec = self.spec(ctx)
        parts = self.parts(spec)
        app = parts.provisioner.find(spec)

        if app is None:
            return

        parts.api.post("application.delete", {"applicationId": app["applicationId"]})
        logger.info("dokploy: deleted %s", app["appName"])

    def verify(self, version: str, stage: str | None = None) -> bool:
        app = self._application(stage)

        if app is None:
            return False

        image = str(app.get("dockerImage") or "")

        return image.endswith(f":{version}") and app.get("applicationStatus") == "done"

    def url(self, version: str, stage: str | None = None) -> str | None:
        spec = self._spec_for(stage)

        try:
            parts = self.parts(spec)
            app = parts.provisioner.find(spec)
        except DeployError:
            return None

        return parts.domains.url_of(app) if app else None

    def _application(self, stage: str | None) -> Record | None:
        spec = self._spec_for(stage)

        return self.parts(spec).provisioner.find(spec)

    def _spec_for(self, stage: str | None) -> Spec:
        """`verify` and `url` come without a context: the last one this target saw, on the stage asked for."""
        base = self._last or Context(repo_root=Path.cwd())

        return Spec.of(replace(base, stage=stage or base.stage or "prod"), self.options)
