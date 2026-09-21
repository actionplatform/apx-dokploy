"""Where a value comes from, in order: the target's own argument, what the deploy job carries (`AP_DOKPLOY_<KEY>` in `ctx.env`), the process environment (`AP_DOKPLOY_<KEY>`, then the plain name such as `DOKPLOY_URL`), the plugin's options file on this machine."""

from __future__ import annotations

import os
from typing import Any

from action_platform.core.exception import ActionPlatformError
from action_platform.plugins.options import FileOptions

from apx_dokploy.client import Dokploy

SLUG = "dokploy"
PLAIN = {"url": "DOKPLOY_URL", "api_key": "DOKPLOY_API_KEY"}


def setting(
    key: str,
    explicit: str | None = None,
    env: dict[str, str] | None = None,
    options: Any | None = None,
) -> str | None:
    name = f"AP_{SLUG}_{key}".upper()
    stored = (options or FileOptions(SLUG)).get(key)
    found = (
        explicit
        or (env or {}).get(name)
        or os.environ.get(name)
        or os.environ.get(PLAIN.get(key, ""))
        or stored
    )

    return str(found) if found else None


def connect(options: Any | None = None) -> Dokploy:
    url = setting("url", options=options)
    key = setting("api_key", options=options)

    if not url or not key:
        raise ActionPlatformError(
            "dokploy: set the plugin's url and api_key options on the platform, "
            "or DOKPLOY_URL and DOKPLOY_API_KEY on a machine"
        )

    return Dokploy(url, key)
