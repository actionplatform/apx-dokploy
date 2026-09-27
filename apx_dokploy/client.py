"""The Dokploy REST API (`/api/<router>.<procedure>`, `x-api-key`) — plain urllib, no client library."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from action_platform.core.exception import DeployError

from apx_dokploy.abc import Api

TIMEOUT = 30


class ApiError(DeployError):
    def __init__(self, status: int, detail: str) -> None:
        hint = (
            " (a wrong key, or one whose rate limit ran out: create it without a rate limit under Settings > API Keys)"
            if status == 401
            else ""
        )
        super().__init__(f"dokploy answered {status}: {detail}{hint}")
        self.status = status
        self.detail = detail


class Dokploy(Api):
    """One Dokploy instance: `get` and `post` against its API with the key."""

    def __init__(self, url: str, api_key: str) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key

    def get(self, procedure: str, **query: Any) -> Any:
        target = f"{self.url}/api/{procedure}"

        if query:
            target += "?" + parse.urlencode(query)

        return self._send("GET", target, None)

    def post(self, procedure: str, body: dict[str, Any] | None = None) -> Any:
        return self._send("POST", f"{self.url}/api/{procedure}", body or {})

    def _send(self, method: str, target: str, body: dict[str, Any] | None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(target, data=data, method=method)
        req.add_header("x-api-key", self.api_key)
        req.add_header("accept", "application/json")

        if data is not None:
            req.add_header("content-type", "application/json")

        try:
            with request.urlopen(req, timeout=TIMEOUT) as response:
                text = response.read().decode(errors="replace")
        except error.HTTPError as e:
            raise ApiError(e.code, e.read().decode(errors="replace")[:500]) from e
        except (error.URLError, TimeoutError) as e:
            raise DeployError(f"dokploy unreachable at {self.url}: {e}") from e

        return json.loads(text) if text.strip() else None
