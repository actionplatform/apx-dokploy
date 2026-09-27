import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from action_platform.core.scaffold.catalog import Matrix, with_plugin_clouds
from action_platform.plugins import Loaded, Plugins, PluginState, registry

from apx_dokploy import DokployPlugin
from apx_dokploy.client import Dokploy
from tests.fake import FakeDokploy


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.plugins = Plugins(
            [Loaded(DokployPlugin(), "apx-dokploy", "0.1.0")],
            PluginState(file=Path(self.tmp.name) / "plugins.json"),
        )
        registry._current = self.plugins
        self.addCleanup(registry.reset)
        self.addCleanup(self.tmp.cleanup)

    def test_tools_are_prefixed_and_read_the_instance(self):
        from action_platform.mcp import server

        fake = FakeDokploy()
        fake.project_create({"name": "shop"})
        mcp = server.build()
        names = {t.name for t in asyncio.run(mcp.list_tools())}

        self.assertTrue(
            {"dokploy_projects", "dokploy_applications", "dokploy_deployments"} <= names
        )

        env = {"DOKPLOY_URL": "https://dokploy.test", "DOKPLOY_API_KEY": "good"}
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(
                Dokploy, "_send", lambda api, m, t, b: fake.send(m, t, b, api.api_key)
            ),
        ):
            result = asyncio.run(mcp.call_tool("dokploy_projects", {}))

        self.assertEqual(json.loads(result.content[0].text)["name"], "shop")

    def test_applications_read_the_full_record(self):
        from apx_dokploy.client import Dokploy as Api
        from apx_dokploy.tools import applications_of

        fake = FakeDokploy()
        project = fake.project_create({"name": "shop"})
        fake.application_create(
            {
                "name": "shop",
                "appName": "shop-production",
                "environmentId": project["environments"][0]["environmentId"],
            }
        )
        api = Api("https://dokploy.test", "good")

        with mock.patch.object(
            Api, "_send", lambda a, m, t, b: fake.send(m, t, b, a.api_key)
        ):
            apps = applications_of(api)

        self.assertEqual(apps[0].app_name, "shop-production-x1y2z3")
        self.assertEqual(apps[0].environment, "production")

    def test_overlay_joins_the_matrix_for_every_language(self):
        merged = with_plugin_clouds(Matrix.from_dict({"clouds": []}))
        cloud = merged.cloud("dokploy")

        self.assertEqual(cloud.source, "dokploy")
        self.assertIn("go", cloud.languages)

    def test_options_declare_the_key_as_a_secret(self):
        kinds = {o.key: o.kind for o in DokployPlugin.options}

        self.assertEqual(kinds["api_key"], "secret")
        self.assertEqual(kinds["url"], "url")
