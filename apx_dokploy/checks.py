"""Readiness: what a deploy needs, checked without changing anything — settings, the published image, the API key, the application's state."""

from __future__ import annotations

from action_platform.core.context import Check
from action_platform.core.exception import DeployError

from apx_dokploy.abc import Api, Provisioner, Readiness, Registry
from apx_dokploy.client import ApiError
from apx_dokploy.spec import Spec


class SettingsCheck(Readiness):
    id = "dokploy.settings"

    def run(self, spec: Spec) -> Check:
        missing = []

        if not spec.url:
            missing.append("url ([deploy] url, the plugin's url option or DOKPLOY_URL)")

        if not spec.api_key:
            missing.append("api key (the plugin's api_key option or DOKPLOY_API_KEY)")

        if not spec.image:
            missing.append("image ([deploy] image or [source_host] repo)")

        if not missing:
            return Check(self.id, True, "url, api key and image are set")

        return Check(
            self.id,
            False,
            "missing " + ", ".join(missing),
            fix="set the plugin options on the platform, or DOKPLOY_URL and DOKPLOY_API_KEY on a machine",
        )


class ImageCheck(Readiness):
    id = "image.published"

    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def run(self, spec: Spec) -> Check:
        try:
            found = self.registry.exists(
                spec.image or "",
                spec.version,
                spec.registry_username,
                spec.registry_password,
            )
        except DeployError as e:
            return Check(
                self.id,
                False,
                str(e),
                severity="warning",
                fix="check the registry and its credentials",
            )

        if found:
            return Check(self.id, True, f"{spec.reference} is in the registry")

        return Check(
            self.id,
            False,
            f"{spec.reference} is not in the registry yet",
            fix="let the image workflow finish on the release tag, then ask for readiness again",
        )


class ApiCheck(Readiness):
    id = "dokploy.credentials"

    def __init__(self, api: Api) -> None:
        self.api = api

    def run(self, spec: Spec) -> Check:
        try:
            self.api.get("project.all")
        except ApiError as e:
            fix = (
                "generate a key under Settings > API Keys in Dokploy and set the plugin's api_key option"
                if e.status in (401, 403)
                else None
            )

            return Check(self.id, False, str(e), fix=fix)
        except DeployError as e:
            return Check(
                self.id,
                False,
                str(e),
                fix="check [deploy] url and that the instance is reachable from the worker",
            )

        return Check(self.id, True, f"{spec.url} accepts the key")


class ApplicationCheck(Readiness):
    id = "dokploy.application"

    def __init__(self, provisioner: Provisioner) -> None:
        self.provisioner = provisioner

    def run(self, spec: Spec) -> Check:
        app = self.provisioner.find(spec)

        if app is None:
            return Check(
                self.id,
                True,
                f"{spec.label} does not exist yet; the deploy creates it",
                severity="warning",
            )

        status = app.get("applicationStatus")

        if status == "running":
            return Check(
                self.id,
                False,
                f"{spec.label} is mid-deployment",
                fix="wait for the running deployment to finish",
            )

        return Check(self.id, True, f"{spec.label} is {status}")
