"""The scope's domain from `[deploy.domains]` over HTTPS; without one, a host Dokploy generates, so every deploy reports a URL."""

from __future__ import annotations

from action_platform.core.exception import DeployError
from action_platform.logging import emit

from apx_dokploy.abc import Api, Domains, Record
from apx_dokploy.spec import Spec


class DokployDomains(Domains):
    def __init__(self, api: Api) -> None:
        self.api = api

    def ensure(self, app: Record, spec: Spec) -> None:
        """Without `[deploy.domains]` for the scope, and while the application has none, Dokploy generates `<app>.<ip>.traefik.me` (plain HTTP)."""
        host = spec.domain
        existing = self._of(app)

        if host:
            if any(d.get("host") == host for d in existing):
                return
        elif existing:
            return
        else:
            host = str(
                self.api.post("domain.generateDomain", {"appName": app["appName"]})
            )

        secure = host in spec.domains.values()
        self.api.post(
            "domain.create",
            {
                "host": host,
                "port": spec.port,
                "https": secure,
                "certificateType": "letsencrypt" if secure else "none",
                "applicationId": app["applicationId"],
                "domainType": "application",
            },
        )
        emit(f"dokploy: domain {host} -> {app['appName']}:{spec.port}")

    def url_of(self, app: Record) -> str | None:
        try:
            domains = self._of(app)
        except DeployError:
            return None

        for domain in sorted(domains, key=lambda d: not d.get("https")):
            if domain.get("host"):
                scheme = "https" if domain.get("https") else "http"

                return f"{scheme}://{domain['host']}{domain.get('path') or ''}"

        return None

    def _of(self, app: Record) -> list[Record]:
        return (
            self.api.get("domain.byApplicationId", applicationId=app["applicationId"])
            or []
        )
