"""The plugin: the dokploy overlay, `action-platform dokploy` commands, `dokploy_*` tools, and the options an organization fills in."""

from __future__ import annotations

from pathlib import Path

from action_platform.abc import Option, Plugin, Surface

from apx_dokploy import cli
from apx_dokploy.tools import register_tools


class DokployPlugin(Plugin):
    slug = "dokploy"
    name = "Dokploy"
    description = (
        "Deploy a Docker image the CI publishes to a Dokploy instance; "
        "read its projects, applications and deployments"
    )
    min_core = "0.28.1"
    needs = [
        "env: DOKPLOY_URL, DOKPLOY_API_KEY on a machine (the plugin's options on the platform)",
        "net: the Dokploy instance's url; the image registry (ghcr.io by default)",
    ]
    options = [
        Option(
            "url",
            "Dokploy URL",
            "url",
            help="Where the Dokploy dashboard answers, https://dokploy.example.com. A project may override it with [deploy] url.",
            required=True,
        ),
        Option(
            "api_key",
            "API key",
            "secret",
            help="Generated under Settings > API Keys in Dokploy. Deploys, creates and deletes applications on your behalf; never written to a repository.",
            required=True,
        ),
        Option(
            "registry_username",
            "Registry username",
            "text",
            help="Only for a private image registry: the user Dokploy pulls with. Empty for a public image.",
        ),
        Option(
            "registry_password",
            "Registry password",
            "secret",
            help="The token that goes with the registry username (a GitHub token with read:packages for ghcr.io).",
        ),
    ]

    @property
    def overlays(self) -> Path:
        return Path(__file__).parent / "overlays"

    def register(self, surface: Surface) -> None:
        if surface.mcp is not None:
            register_tools(surface.mcp, surface.options)

        if surface.cli is not None:
            cli.options = surface.options
            surface.cli.add_typer(cli.app, name="dokploy")
