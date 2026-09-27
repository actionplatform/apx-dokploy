"""What one deploy call is about, resolved once from the target's options, `platform.toml` and the settings chain — no state kept between calls."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from action_platform.core.context import Context

from apx_dokploy.settings import setting


@dataclass(frozen=True)
class Options:
    """What `[deploy]` in platform.toml passes to the target."""

    url: str | None = None
    api_key: str | None = None
    image: str | None = None
    project: str | None = None
    application: str | None = None
    port: int = 8000
    domains: dict[str, str] = field(default_factory=dict)
    registry_username: str | None = None
    registry_password: str | None = None
    health: str = "/health"


@dataclass(frozen=True)
class Spec:
    stage: str
    version: str
    url: str | None
    api_key: str | None
    image: str | None
    project: str
    application: str
    port: int
    domains: dict[str, str]
    registry_username: str | None
    registry_password: str | None
    health: str = "/health"

    @classmethod
    def of(cls, ctx: Context, options: Options) -> Spec:
        manifest = _manifest(ctx.repo_root)
        name = str(manifest.get("project", {}).get("name") or ctx.repo_root.name)
        name = name.lower().replace(" ", "-")
        repo = str(manifest.get("source_host", {}).get("repo") or "")
        image = options.image or (f"ghcr.io/{repo.lower()}" if repo else None)

        return cls(
            stage=ctx.stage or "prod",
            version=ctx.next_version,
            url=setting("url", options.url, ctx.env),
            api_key=setting("api_key", options.api_key, ctx.env),
            image=image,
            project=options.project or name,
            application=options.application or name,
            port=int(options.port),
            domains=dict(options.domains),
            registry_username=setting(
                "registry_username", options.registry_username, ctx.env
            ),
            registry_password=setting(
                "registry_password", options.registry_password, ctx.env
            ),
            health=options.health,
        )

    @property
    def app_name(self) -> str:
        """The appName asked for; Dokploy stores it with a random suffix."""
        return f"{self.application}-{self.stage}"

    @property
    def reference(self) -> str:
        return f"{self.image}:{self.version}"

    @property
    def label(self) -> str:
        return f"{self.project}/{self.stage}/{self.application}"

    @property
    def domain(self) -> str | None:
        return self.domains.get(self.stage)


def _manifest(root: Path) -> dict[str, Any]:
    path = root / "platform.toml"

    return tomllib.loads(path.read_text()) if path.exists() else {}
