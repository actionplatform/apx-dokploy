"""Access on a Dokploy instance: organization membership with its role, and which projects a member may open."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from action_platform.abc import AccessProvider
from action_platform.core.exception import DeployError
from action_platform.core.service_access import AccessError, Grant, Op

from apx_dokploy.abc import Api
from apx_dokploy.client import ApiError

FLAGS = (
    "canCreateProjects",
    "canCreateServices",
    "canDeleteProjects",
    "canDeleteServices",
    "canAccessToDocker",
    "canAccessToTraefikFiles",
    "canAccessToAPI",
    "canAccessToSSHKeys",
    "canAccessToGitProviders",
    "canDeleteEnvironments",
    "canCreateEnvironments",
)
LISTS = (
    "accessedProjects",
    "accessedEnvironments",
    "accessedServices",
    "accessedGitProviders",
    "accessedServers",
)


class DokployAccess(AccessProvider):
    """Accounts are user emails. `org` is `member` or `admin` (the owner is read, never changed); `project/<name>` opens one project and its environments to a member — owners and admins see every project already. An added member gets an invitation and counts as granted while it is pending and unexpired; projects follow once it is accepted. Removing a member is Dokploy's `user.remove`, which on a self-hosted instance deletes the user."""

    name = "dokploy"
    levels = {"org": ("member", "admin", "owner"), "project": ("access",)}

    def __init__(self, api: Api) -> None:
        self.api = api

    def read(self) -> list[Grant]:
        grants: list[Grant] = []
        names = {p["projectId"]: p["name"] for p in self._projects()}

        for m in self._members():
            email = (m.get("user") or {}).get("email", "").lower()

            if not email:
                continue

            grants.append(Grant("dokploy", email, "org", m.get("role") or "member"))

            if m.get("role") == "member":
                for pid in m.get("accessedProjects") or []:
                    if pid in names:
                        grants.append(
                            Grant("dokploy", email, f"project/{names[pid]}", "access")
                        )

        for inv in self._invitations():
            if _open(inv) and inv.get("email"):
                grants.append(
                    Grant(
                        "dokploy",
                        inv["email"].lower(),
                        "org",
                        inv.get("role") or "member",
                    )
                )

        return self.strongest(grants)

    def apply(self, op: Op) -> None:
        g = op.grant
        kind, _, target = g.resource.partition("/")

        if kind == "org":
            self._org(op)
        elif kind == "project":
            self._project(g.account, target, op.action != "remove")
        else:
            raise AccessError(f"dokploy: cannot apply {g.resource}")

    def expand(self, grants: set[Grant]) -> set[Grant]:
        seeing_all = {
            g.account.lower()
            for g in grants
            if g.resource == "org" and g.level in ("admin", "owner")
        }

        return {
            g
            for g in grants
            if not (
                self.kind(g.resource) == "project" and g.account.lower() in seeing_all
            )
        }

    def guard(self, ops: list[Op], live: list[Grant]) -> dict[Op, str]:
        owners = {
            g.account.lower()
            for g in live
            if g.resource == "org" and g.level == "owner"
        }

        return {
            op: f"dokploy: {op.grant.account} owns the instance; the owner is never changed here"
            for op in ops
            if op.grant.resource == "org"
            and (op.grant.account.lower() in owners or op.grant.level == "owner")
        }

    def _org(self, op: Op) -> None:
        g = op.grant

        if op.action == "add":
            stale = self._invitation(g.account)

            if stale is not None:
                self._post(
                    "organization.removeInvitation", {"invitationId": stale["id"]}
                )

            self._post(
                "organization.inviteMember", {"email": g.account, "role": g.level}
            )
            return

        member = self._member(g.account)

        if member is None:
            invitation = self._invitation(g.account)

            if invitation is None or op.action != "remove":
                raise AccessError(
                    f"dokploy: {g.account} has not accepted the invitation yet"
                )

            self._post(
                "organization.removeInvitation", {"invitationId": invitation["id"]}
            )
        elif op.action == "change":
            self._post(
                "organization.updateMemberRole",
                {"memberId": member["id"], "role": g.level},
            )
        else:
            self._post("user.remove", {"userId": member["userId"]})

    def _project(self, email: str, name: str, on: bool) -> None:
        member = self._member(email)

        if member is None:
            raise AccessError(
                f"dokploy: {email} is not a member yet — the invitation has to be accepted first"
            )

        project = next((p for p in self._projects() if p["name"] == name), None)

        if project is None:
            raise AccessError(f"dokploy: no project named {name!r}")

        environments = {e["environmentId"] for e in project.get("environments") or []}
        body: dict[str, Any] = {"id": member["userId"]}
        body.update({flag: bool(member.get(flag)) for flag in FLAGS})
        body.update({key: list(member.get(key) or []) for key in LISTS})
        projects, envs = (
            set(body["accessedProjects"]),
            set(body["accessedEnvironments"]),
        )

        if on:
            projects.add(project["projectId"])
            envs |= environments
        else:
            projects.discard(project["projectId"])
            envs -= environments

        body["accessedProjects"], body["accessedEnvironments"] = (
            sorted(projects),
            sorted(envs),
        )
        self._post("user.assignPermissions", body)

    def _get(self, procedure: str) -> Any:
        try:
            return self.api.get(procedure)
        except DeployError as e:
            raise _failure(procedure, e) from e

    def _post(self, procedure: str, body: dict[str, Any]) -> Any:
        try:
            return self.api.post(procedure, body)
        except DeployError as e:
            raise _failure(procedure, e) from e

    def _members(self) -> list[dict]:
        return list(self._get("user.all") or [])

    def _projects(self) -> list[dict]:
        return list(self._get("project.all") or [])

    def _invitations(self) -> list[dict]:
        return list(self._get("organization.allInvitations") or [])

    def _member(self, email: str) -> Optional[dict]:
        return next(
            (
                m
                for m in self._members()
                if (m.get("user") or {}).get("email", "").lower() == email.lower()
            ),
            None,
        )

    def _invitation(self, email: str) -> Optional[dict]:
        return next(
            (
                i
                for i in self._invitations()
                if i.get("status") == "pending"
                and (i.get("email") or "").lower() == email.lower()
            ),
            None,
        )


def _failure(procedure: str, error: DeployError) -> AccessError:
    if isinstance(error, ApiError):
        return AccessError(
            f"dokploy: {procedure} answered {error.status}: {error.detail}"
        )

    return AccessError(str(error))


def _open(invitation: dict) -> bool:
    if invitation.get("status") != "pending":
        return False

    expires = str(invitation.get("expiresAt") or "")

    if not expires:
        return True

    try:
        moment = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return True

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment > datetime.now(timezone.utc)
