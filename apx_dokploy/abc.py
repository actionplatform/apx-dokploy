"""The responsibilities a Dokploy deploy is made of, one contract each; `DokployTarget` composes an implementation of every one."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from action_platform.core.context import Check

    from apx_dokploy.spec import Spec

Record = dict[str, Any]


class Api(ABC):
    """A Dokploy instance's API: procedures read with `get`, changed with `post`."""

    @abstractmethod
    def get(self, procedure: str, **query: Any) -> Any: ...

    @abstractmethod
    def post(self, procedure: str, body: dict[str, Any] | None = None) -> Any: ...


class Registry(ABC):
    """Where the image lives: whether a tag of it has been published."""

    @abstractmethod
    def exists(
        self,
        image: str,
        tag: str,
        username: str | None = None,
        password: str | None = None,
    ) -> bool: ...


class Provisioner(ABC):
    """The project, the scope's environment and the application inside it."""

    @abstractmethod
    def find(self, spec: Spec) -> Record | None:
        """The application of the scope, or None when any level is missing."""

    @abstractmethod
    def ensure(self, spec: Spec) -> Record:
        """The application of the scope, creating whatever level is missing."""


class Domains(ABC):
    """How the application is reached."""

    @abstractmethod
    def ensure(self, app: Record, spec: Spec) -> None: ...

    @abstractmethod
    def url_of(self, app: Record) -> str | None: ...


class Deployments(ABC):
    """Running a version on the application and reading what ran."""

    @abstractmethod
    def start(self, app: Record, spec: Spec) -> None:
        """Point the application at `spec.reference` and ask for a deployment."""

    @abstractmethod
    def wait(self, app: Record) -> str:
        """Block until the deployment ends; its final status."""

    @abstractmethod
    def previous_version(self, app: Record) -> str | None:
        """The newest version that deployed fine before the current one."""

    @abstractmethod
    def failure(self, app: Record) -> str | None:
        """Why the latest deployment failed: its error and the tail of its log."""


class Readiness(ABC):
    """One check a deploy needs to pass, run without changing anything."""

    id: str

    @abstractmethod
    def run(self, spec: Spec) -> Check: ...
