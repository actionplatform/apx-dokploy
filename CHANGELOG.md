# Changelog

## v0.5.0 — 2026-09-27

### Bug Fixes
- **overlay:** take the package's architecture from the build stage

## v0.4.0 — 2026-09-27

### Features
- **provision:** deleting a scope removes what it leaves empty
- **deployments:** [deploy.env] sets the application's environment
- **health:** a deploy succeeds only once the app answers
- **provision:** report duplicate applications in a scope
- **deployments:** a failed deploy says why

### Bug Fixes
- **client:** a 401 names the API key's rate limit
- **deployments:** send the registry with private registry credentials
- **tools:** read an application's appName and image from application.one

### Refactoring
- one ABC per responsibility, the target composes them

### Tests
- create the CI API key without better-auth's rate limit
- probe the API key against Dokploy's routes
- show the shape of Dokploy's createApiKey answer
- run the target against a real Dokploy in CI

## v0.3.2 — 2026-09-27

### Bug Fixes
- **target:** find the application by name; project.all has no appName

## v0.3.1 — 2026-09-27

### Bug Fixes
- **target:** find the application Dokploy renamed with a suffix

## v0.3.0 — 2026-09-27

### Features
- **target:** every Dokploy deploy reports a URL

## v0.2.0 — 2026-09-27

### Features
- **overlay:** the Dockerfile names the language version

### Tests
- import the matrix from scaffold.catalog, where action-platform 0.32 keeps it

## v0.1.0 — 2026-09-21

### Features
- dokploy deploy target, overlay, readiness checks and read tools

### CI
- require action-platform 0.28.1, the newest on PyPI

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
