"""The Dokploy REST API (`/api/<router>.<procedure>`, `x-api-key`) and the OCI registry the image lives in — plain urllib, no client library."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib import error, parse, request

from action_platform.core.exception import DeployError

TIMEOUT = 30
MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class ApiError(DeployError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"dokploy answered {status}: {detail}")
        self.status = status
        self.detail = detail


class Dokploy:
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


def image_exists(
    image: str,
    tag: str,
    username: str | None = None,
    password: str | None = None,
) -> bool:
    """Whether `image:tag` is in its registry — a manifest HEAD, with the bearer token the registry asks for when it asks for one."""
    registry, name = _split(image)
    target = f"https://{registry}/v2/{name}/manifests/{tag}"
    basic = (
        base64.b64encode(f"{username}:{password}".encode()).decode()
        if username and password
        else None
    )
    status, challenge = _head(target, "Basic " + basic if basic else None)

    if status == 401 and challenge:
        token = _token(challenge, basic)
        status, _ = _head(target, f"Bearer {token}")

    if status == 200:
        return True

    if status == 404:
        return False

    raise DeployError(f"registry {registry} answered {status} for {name}:{tag}")


def _split(image: str) -> tuple[str, str]:
    head, _, rest = image.partition("/")

    if rest and ("." in head or ":" in head or head == "localhost"):
        return head, rest

    name = image if "/" in image else f"library/{image}"

    return "registry-1.docker.io", name


def _head(target: str, authorization: str | None) -> tuple[int, str]:
    req = request.Request(target, method="HEAD")
    req.add_header("accept", MANIFEST_TYPES)

    if authorization:
        req.add_header("authorization", authorization)

    try:
        with request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status, ""
    except error.HTTPError as e:
        return e.code, e.headers.get("www-authenticate", "")
    except (error.URLError, TimeoutError) as e:
        raise DeployError(f"registry unreachable: {e}") from e


def _token(challenge: str, basic: str | None) -> str:
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = fields.get("realm")

    if not realm:
        raise DeployError(f"registry challenge not understood: {challenge}")

    query = {k: v for k, v in fields.items() if k in ("service", "scope")}
    req = request.Request(f"{realm}?{parse.urlencode(query)}")

    if basic:
        req.add_header("authorization", f"Basic {basic}")

    try:
        with request.urlopen(req, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode())
    except error.HTTPError as e:
        raise DeployError(f"registry token refused ({e.code}): check the credentials")

    return data.get("token") or data.get("access_token") or ""
