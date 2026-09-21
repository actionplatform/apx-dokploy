# apx-dokploy

[Dokploy](https://dokploy.com) for [Action Platform](https://github.com/actionplatform/action-platform): the `dokploy` deploy target, its overlay, readiness checks, and tools that read what runs on the instance. `apx-` is the prefix every Action Platform extension carries.

```bash
action-platform plugin install dokploy
export DOKPLOY_URL=… DOKPLOY_API_KEY=…      # or Plugins → Dokploy → Configure on the platform
action-platform cloud set dokploy               # Dockerfile, compose file, image workflow
action-platform deploy --dry-run                # readiness: settings, image, key, application
action-platform deploy                          # point Dokploy at <image>:<version>, follow to done
action-platform diagnose
```

## How it works

The build never runs on the platform or on Dokploy. The overlay's workflow publishes `ghcr.io/<owner>/<repo>:<version>` on every published release; the target tells Dokploy which tag to run and waits for the deployment to end. Every deployment therefore references a release, and rolling back is pointing at the previous tag.

| | |
|---|---|
| Overlay | `Dockerfile` (two stages on the [images-base](https://github.com/actionplatform/images-base) build and runtime images, `ap-build package`, port 8000), `.dockerignore`, `docker-compose.yml` for a machine, `.github/workflows/docker-publish.yml` (GitHub CI only), `DEPLOY.md`. One overlay for every language of the official `web/*` templates |
| Mapping | Dokploy project = `[project] name`; environment = the scope (`dev`, `prod`); application = `<name>-<scope>`. `create` and the first `deploy` provision what is missing, the domain included when `[deploy.domains]` names one |
| Readiness | `dokploy.settings` (url, key, image known), `image.published` (a manifest HEAD at the registry, following the bearer challenge), `dokploy.credentials` (the key opens `project.all`), `dokploy.application` (exists, not mid-deployment). The platform runs it after every release and refuses a blocked deploy |
| Deploy | `application.saveDockerProvider` with `<image>:<version>`, `application.deploy` titled `v<version>`, then `application.one` until `done` or `error` (15 minutes at most). Every step reaches the platform's run log |
| Rollback | the previous `done` deployment titled `v<version>` in the history, or the version asked for, deployed again |
| Diagnose | status, image, version and url of the scope's application |
| Delete | `application.delete` of the scope's application |
| Tools | `dokploy_projects`, `dokploy_applications`, `dokploy_deployments` |
| Commands | `action-platform dokploy projects\|applications\|deployments` |

## Configuration

`platform.toml`:

```toml
[deploy]
target = "dokploy"
# url = "https://dokploy.example.com"    # overrides the plugin option
# image = "ghcr.io/acme/shop"            # default: ghcr.io/<[source_host] repo>
# project = "shop"                       # default: [project] name
# application = "shop"                   # default: [project] name
# port = 8000

[deploy.domains]
prod = "shop.example.com"
dev = "shop-dev.example.com"
```

Plugin options (Plugins → Dokploy → Configure on the platform; on a machine, the environment or `~/.action-platform/plugins/dokploy.json`):

| Option | Environment | |
|---|---|---|
| `url` | `DOKPLOY_URL` | where the dashboard answers. Order on a machine: `[deploy]`, `AP_DOKPLOY_URL`, `DOKPLOY_URL`, the options file |
| `api_key` | `DOKPLOY_API_KEY` | Settings → API Keys in Dokploy. Never in `platform.toml` |
| `registry_username`, `registry_password` | `AP_DOKPLOY_REGISTRY_*` | only for a private image; a GitHub token with `read:packages` for ghcr.io |

A deploy job carries the options as `AP_DOKPLOY_<KEY>`.

## Requirements

- Dokploy 0.20 or newer (projects with environments; `application.saveDockerProvider`).
- The image published before the deploy: on GitHub, the overlay's workflow does it on every release. Another CI publishes `<image>:<version>` itself; the `image.published` check waits for it.
- The container listens on `$PORT` (8000 in the overlay's Dockerfile).

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

Tests never reach the network: `tests/fake.py` is a Dokploy in memory.
