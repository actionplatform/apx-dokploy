# Deploy — Dokploy

Overlay `cloud/dokploy`. The CI builds the image on every release and Dokploy pulls it; the platform tells Dokploy which tag to run.

| | |
|---|---|
| Image | `ghcr.io/{{ cookiecutter.github_owner }}/{{ cookiecutter.project_slug }}:<version>` — `.github/workflows/docker-publish.yml`, on every published release |
| Dokploy project | `{{ cookiecutter.project_slug }}` |
| Dokploy environment | one per scope: `dev`, `prod` |
| Application | `{{ cookiecutter.project_slug }}-<scope>`, listens on port 8000 |

## Set up once

1. In Dokploy, Settings → API Keys: create a key. Put it and the instance url in the plugin's options (Plugins → Dokploy → Configure on the platform; `DOKPLOY_URL` and `DOKPLOY_API_KEY` on a machine).
2. Is the GitHub package private? Give the plugin a registry username and a token with `read:packages`, or make the package public under the repository's Packages settings.
3. `platform.toml`:

```toml
[deploy]
target = "dokploy"

[deploy.domains]
prod = "{{ cookiecutter.project_slug }}.example.com"
```

The first deploy creates the project, the environment, the application and the domain (Let's Encrypt). Point the DNS record at the Dokploy server before that.

## Every release

```bash
action-platform release minor        # tags vX.Y.Z; the workflow publishes the image
action-platform deploy --dry-run     # readiness: settings, image published, key accepted, application state
action-platform deploy               # saveDockerProvider(<image>:<version>) + deploy, followed to done
```

`rollback` redeploys the previous version from the application's deployment history; `diagnose` reports the status, the image and the url.

## Locally

```bash
docker compose up --build            # http://localhost:8000
```
