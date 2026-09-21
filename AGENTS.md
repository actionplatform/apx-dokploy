# AGENTS.md

Rules an AI agent (or a new contributor) follows in this repository.

## What this is

`apx-dokploy`, an Action Platform plugin: the `dokploy` deploy target, its cloud overlay, `dokploy_*` tools and `action-platform dokploy` commands. The contract every plugin follows is `SPEC.md` in [apx-example](https://github.com/actionplatform/apx-example); read it before changing the shape of anything here.

## How a deploy works

The CI publishes `<image>:<version>` on every release (`docker-publish.yml` from the overlay). The target never builds: it points the Dokploy application at that tag (`application.saveDockerProvider`), asks for a deploy (`application.deploy`) and follows `applicationStatus` to `done` or `error`. One Dokploy project per repository, one environment per scope, one application per environment. The API key is a plugin option, never a file in a repository.

## Code

- Python 3.11+, `ruff check . && ruff format --check .`, `pytest` green before a commit.
- No comments inside function bodies; no test docstrings. Module docstrings say what the module is for.
- `register` declares only — no I/O at import or in `register`.
- Never monkey-patch `action_platform.*`.
- Talk to Dokploy through `client.Dokploy` only; tests drive `tests/fake.py`, never the network.
- `needs` lists every host and environment variable the plugin touches.

## Commits and branches

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): description`; one commit per concern. Git-flow: `<kind>/<issue>-<slug>` from `master`, kinds `feature bugfix hotfix release chore docs refactor test ci perf`; never commit on `master`. One pull request per issue.

## Release

`action-platform release <level>`; the tag publishes to PyPI; then a PR to `plugins-index` with the new `latest`.
