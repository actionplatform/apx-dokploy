import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from action_platform.core.context import Context
from action_platform.core.exception import DeployError
from action_platform.plugins.options import FileOptions

from apx_dokploy import deployments, registry
from apx_dokploy import target as target_module
from apx_dokploy.client import Dokploy
from apx_dokploy.target import DokployTarget
from tests.fake import FakeDokploy

MANIFEST = """
[project]
name = "shop"
type = "web"
language = "python"

[source_host]
kind = "github"
repo = "Acme/Shop"

[deploy]
target = "dokploy"
"""


class TargetCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "platform.toml").write_text(MANIFEST)
        self.fake = FakeDokploy()
        self.addCleanup(self.tmp.cleanup)
        self._patch(
            Dokploy,
            "_send",
            lambda api, method, target, body: self.fake.send(
                method, target, body, api.api_key
            ),
        )
        self._patch(registry, "image_exists", lambda *a, **k: True)
        self._patch(deployments, "POLL", 0)
        self.home = TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self._patch(os, "environ", {"AP_HOME": self.home.name})

    def _patch(self, obj, name, value):
        patcher = mock.patch.object(obj, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ctx(
        self, stage="prod", version="1.2.0", key="good", url="https://dokploy.test"
    ):
        env = {"AP_DOKPLOY_URL": url, "AP_DOKPLOY_API_KEY": key} if key else {}

        return Context(repo_root=self.root, stage=stage, next_version=version, env=env)


class ReadinessTest(TargetCase):
    def test_missing_settings_is_the_only_check(self):
        checks = DokployTarget().readiness(self.ctx(key=None, url=None))

        self.assertEqual([c.id for c in checks], ["dokploy.settings"])
        self.assertFalse(checks[0].ok)
        self.assertIn("api key", checks[0].detail)

    def test_bad_key_names_the_fix(self):
        checks = {c.id: c for c in DokployTarget().readiness(self.ctx(key="bad"))}

        self.assertFalse(checks["dokploy.credentials"].ok)
        self.assertIn("API Keys", checks["dokploy.credentials"].fix)
        self.assertNotIn("dokploy.application", checks)

    def test_unpublished_image_blocks(self):
        self._patch(registry, "image_exists", lambda *a, **k: False)

        checks = {c.id: c for c in DokployTarget().readiness(self.ctx())}

        self.assertTrue(checks["image.published"].blocking)
        self.assertIn("ghcr.io/acme/shop:1.2.0", checks["image.published"].detail)

    def test_absent_application_is_a_warning(self):
        checks = {c.id: c for c in DokployTarget().readiness(self.ctx())}

        self.assertTrue(checks["dokploy.application"].ok)
        self.assertEqual(checks["dokploy.application"].severity, "warning")
        self.assertIn("shop/prod/shop", checks["dokploy.application"].detail)

    def test_duplicate_applications_are_a_warning_naming_them(self):
        target = DokployTarget()
        target.deploy(self.ctx())
        env = self.fake.projects[0]["environments"][1]
        self.fake.application_create(
            {
                "name": "shop",
                "appName": "shop-prod",
                "environmentId": env["environmentId"],
            }
        )
        env["applications"][1]["applicationId"] = "second"

        checks = {c.id: c for c in target.readiness(self.ctx())}

        self.assertEqual(checks["dokploy.application"].severity, "warning")
        self.assertIn("2 applications", checks["dokploy.application"].detail)
        self.assertIn("second", checks["dokploy.application"].fix)

    def test_preflight_raises_on_a_blocking_check(self):
        with self.assertRaises(DeployError) as raised:
            DokployTarget().preflight(self.ctx(key="bad"))

        self.assertIn("dokploy.credentials", str(raised.exception))


class DeployTest(TargetCase):
    def test_first_deploy_creates_project_environment_application_and_domain(self):
        target = DokployTarget(domains={"prod": "shop.example.com"})

        result = target.deploy(self.ctx())

        self.assertTrue(result.ok)
        self.assertEqual(result.version, "1.2.0")
        self.assertEqual(result.url, "https://shop.example.com")
        procedures = [c[1] for c in self.fake.calls]
        self.assertEqual(
            [p for p in procedures if p.endswith("create")],
            [
                "project.create",
                "environment.create",
                "application.create",
                "domain.create",
            ],
        )
        app = self.fake.projects[0]["environments"][1]["applications"][0]
        self.assertEqual(app["appName"], "shop-prod-x1y2z3")
        self.assertEqual(app["dockerImage"], "ghcr.io/acme/shop:1.2.0")
        deploy = next(c for c in self.fake.calls if c[1] == "application.deploy")
        self.assertEqual(deploy[2]["title"], "v1.2.0")

    def test_second_deploy_reuses_what_exists(self):
        target = DokployTarget()
        target.deploy(self.ctx())
        self.fake.calls.clear()

        target.deploy(self.ctx(version="1.3.0"))

        self.assertFalse([c for c in self.fake.calls if c[1].endswith("create")])
        self.assertTrue(target.verify("1.3.0", "prod"))
        self.assertFalse(target.verify("1.2.0", "prod"))

    def test_without_a_domain_dokploy_generates_one_once(self):
        target = DokployTarget()

        result = target.deploy(self.ctx())
        target.deploy(self.ctx(version="1.3.0"))

        self.assertEqual(
            result.url, "http://shop-prod-x1y2z3-1a2b3c-203-0-113-7.traefik.me"
        )
        generated = [c for c in self.fake.calls if c[1] == "domain.generateDomain"]
        self.assertEqual(len(generated), 1)
        created = next(c for c in self.fake.calls if c[1] == "domain.create")
        self.assertFalse(created[2]["https"])

    def test_a_configured_domain_reaches_an_application_that_already_exists(self):
        DokployTarget().deploy(self.ctx())

        result = DokployTarget(domains={"prod": "shop.example.com"}).deploy(
            self.ctx(version="1.3.0")
        )

        hosts = [d["host"] for d in self.fake.domains["ashop-prod"]]
        self.assertIn("shop.example.com", hosts)
        self.assertEqual(result.url, "https://shop.example.com")

    def test_deploys_reuse_the_application_dokploy_renamed(self):
        target = DokployTarget()
        target.deploy(self.ctx())
        target.deploy(self.ctx(version="1.3.0"))

        creates = [c for c in self.fake.calls if c[1] == "application.create"]
        self.assertEqual(len(creates), 1)

    def test_failed_deployment_is_reported_with_its_reason(self):
        self.fake.deploy_ends = "error"

        with mock.patch.object(target_module, "emit") as said:
            result = DokployTarget().deploy(self.ctx())

        self.assertFalse(result.ok)
        self.assertIn("container exited with code 1", result.error)
        self.assertIn("address already in use", said.call_args.args[0])

    def test_an_unpublished_image_stops_the_deploy_before_dokploy(self):
        self._patch(registry, "image_exists", lambda *a, **k: False)

        with self.assertRaises(DeployError) as raised:
            DokployTarget().deploy(self.ctx())

        self.assertIn(
            "ghcr.io/acme/shop:1.2.0 is not in the registry", str(raised.exception)
        )
        self.assertFalse([c for c in self.fake.calls if c[1] == "application.deploy"])

    def test_stages_are_separate_environments(self):
        target = DokployTarget()
        target.deploy(self.ctx(stage="dev"))
        target.deploy(self.ctx(stage="prod"))

        names = [e["name"] for e in self.fake.projects[0]["environments"]]
        self.assertEqual(names, ["production", "dev", "prod"])

    def test_private_registry_credentials_reach_the_provider(self):
        ctx = self.ctx()
        ctx.env.update(
            {
                "AP_DOKPLOY_REGISTRY_USERNAME": "bot",
                "AP_DOKPLOY_REGISTRY_PASSWORD": "tok",
            }
        )

        DokployTarget().deploy(ctx)

        provider = next(
            c for c in self.fake.calls if c[1] == "application.saveDockerProvider"
        )
        self.assertEqual(
            (provider[2]["username"], provider[2]["password"]), ("bot", "tok")
        )


class LifecycleTest(TargetCase):
    def test_rollback_goes_to_the_previous_done_version(self):
        target = DokployTarget()
        target.deploy(self.ctx(version="1.0.0"))
        target.deploy(self.ctx(version="1.1.0"))

        target.rollback(self.ctx(version="1.1.0"))

        self.assertTrue(target.verify("1.0.0", "prod"))

    def test_rollback_without_history_refuses(self):
        with self.assertRaises(DeployError):
            DokployTarget().rollback(self.ctx())

    def test_diagnose_and_delete(self):
        target = DokployTarget()
        self.assertEqual(target.diagnose(self.ctx()).status, "missing")

        target.deploy(self.ctx())
        diagnosis = target.diagnose(self.ctx())

        self.assertTrue(diagnosis.ok)
        self.assertEqual(diagnosis.version, "1.2.0")
        self.assertEqual(diagnosis.details["application"], "shop-prod-x1y2z3")

        target.delete(self.ctx())

        self.assertEqual(target.diagnose(self.ctx()).status, "missing")
        target.delete(self.ctx())

    def test_options_from_platform_toml_win(self):
        target = DokployTarget(
            project="acme", application="api", image="registry.example.com/acme/api"
        )
        spec = target.spec(self.ctx())

        self.assertEqual(spec.project, "acme")
        self.assertEqual(spec.app_name, "api-prod")
        self.assertEqual(spec.image, "registry.example.com/acme/api")


class SettingsTest(TargetCase):
    def test_options_file_is_the_last_resort(self):
        FileOptions("dokploy").set("url", "https://file.test")
        FileOptions("dokploy").set("api_key", "good")

        checks = {
            c.id: c for c in DokployTarget().readiness(self.ctx(key=None, url=None))
        }

        self.assertTrue(checks["dokploy.credentials"].ok)
        self.assertIn("file.test", checks["dokploy.credentials"].detail)

    def test_job_env_wins_over_the_file(self):
        FileOptions("dokploy").set("api_key", "bad")

        checks = {c.id: c for c in DokployTarget().readiness(self.ctx())}

        self.assertTrue(checks["dokploy.credentials"].ok)


class RegistryTest(unittest.TestCase):
    def test_bearer_challenge_is_followed(self):
        answers = iter(
            [
                (
                    401,
                    'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:acme/shop:pull"',
                ),
                (200, ""),
            ]
        )
        with (
            mock.patch.object(registry, "_head", lambda target, auth: next(answers)),
            mock.patch.object(registry, "_token", lambda challenge, basic: "t"),
        ):
            self.assertTrue(registry.image_exists("ghcr.io/acme/shop", "1.0.0"))

    def test_missing_tag_is_false_and_other_statuses_raise(self):
        with mock.patch.object(registry, "_head", lambda target, auth: (404, "")):
            self.assertFalse(registry.image_exists("ghcr.io/acme/shop", "1.0.0"))

        with mock.patch.object(registry, "_head", lambda target, auth: (500, "")):
            with self.assertRaises(DeployError):
                registry.image_exists("ghcr.io/acme/shop", "1.0.0")

    def test_docker_hub_and_custom_registries_split(self):
        self.assertEqual(
            registry._split("nginx"), ("registry-1.docker.io", "library/nginx")
        )
        self.assertEqual(
            registry._split("acme/shop"), ("registry-1.docker.io", "acme/shop")
        )
        self.assertEqual(registry._split("ghcr.io/acme/shop"), ("ghcr.io", "acme/shop"))
        self.assertEqual(
            registry._split("localhost:5000/shop"), ("localhost:5000", "shop")
        )


class PartsTest(TargetCase):
    def test_one_responsibility_is_swapped_without_touching_the_rest(self):
        from dataclasses import replace as swap

        from apx_dokploy.abc import Deployments

        class Instant(Deployments):
            def start(self, app, spec):
                self.started = spec.reference

            def wait(self, app):
                return "done"

            def previous_version(self, app):
                return None

            def failure(self, app):
                return None

        instant = Instant()

        class Target(DokployTarget):
            def parts(self, spec):
                return swap(super().parts(spec), deployments=instant)

        result = Target().deploy(self.ctx())

        self.assertTrue(result.ok)
        self.assertEqual(instant.started, "ghcr.io/acme/shop:1.2.0")
        self.assertFalse([c for c in self.fake.calls if c[1] == "application.deploy"])
