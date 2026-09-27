"""Against a real Dokploy (DOKPLOY_URL and DOKPLOY_API_KEY set, as the live workflow does); skipped elsewhere."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from action_platform.core.context import Context

from apx_dokploy.target import DokployTarget

LIVE = bool(os.environ.get("DOKPLOY_URL") and os.environ.get("DOKPLOY_API_KEY"))
IMAGE = "ghcr.io/actionplatform/web-go-gin"
VERSION = "0.1.0"


@unittest.skipUnless(LIVE, "needs a Dokploy: DOKPLOY_URL and DOKPLOY_API_KEY")
class LiveDokployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "platform.toml").write_text(
            '[project]\nname = "live-check"\n\n[deploy]\ntarget = "dokploy"\n'
        )
        self.target = DokployTarget(image=IMAGE, health="")
        self.ctx = Context(repo_root=root, stage="ci", next_version=VERSION)

    def test_two_deploys_keep_one_application_and_delete_clears_the_project(self):
        first = self.target.deploy(self.ctx)
        second = self.target.deploy(self.ctx)

        self.assertTrue(first.ok, first.error)
        self.assertTrue(second.ok, second.error)
        self.assertTrue(first.url)

        spec = self.target.spec(self.ctx)
        provisioner = self.target.parts(spec).provisioner

        self.assertIsNotNone(provisioner.find(spec))
        self.assertEqual(provisioner.duplicates(spec), [])
        self.assertTrue(self.target.verify(VERSION, "ci"))

        self.target.delete(self.ctx)

        self.assertIsNone(provisioner.find(spec))
        self.assertIsNone(provisioner._project(spec))
