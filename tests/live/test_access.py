"""Access against the real Dokploy the live workflow brings up (DOKPLOY_URL and DOKPLOY_API_KEY set); skipped elsewhere."""

import os
import unittest

from action_platform.core.service_access import Grant, Op

from apx_dokploy import DokployPlugin
from apx_dokploy.access import DokployAccess

LIVE = bool(os.environ.get("DOKPLOY_URL") and os.environ.get("DOKPLOY_API_KEY"))
THROWAWAY = "access-check@example.com"


class Options:
    def get(self, key, default=None):
        return {
            "url": os.environ.get("DOKPLOY_URL"),
            "api_key": os.environ.get("DOKPLOY_API_KEY"),
        }.get(key, default)


@unittest.skipUnless(LIVE, "needs a Dokploy: DOKPLOY_URL and DOKPLOY_API_KEY")
class LiveAccessTest(unittest.TestCase):
    def setUp(self):
        self.provider = DokployPlugin().access(Options())
        self.addCleanup(self.clean)

    def clean(self):
        if any(g.account == THROWAWAY for g in self.provider.read()):
            self.provider.apply(
                Op("remove", Grant("dokploy", THROWAWAY, "org", "member"))
            )

    def test_the_provider_is_built_from_the_options(self):
        self.assertIsInstance(self.provider, DokployAccess)

    def test_the_instance_has_an_owner(self):
        grants = self.provider.read()

        owners = [g for g in grants if g.resource == "org" and g.level == "owner"]
        self.assertTrue(owners)
        self.assertTrue(all(g.service == "dokploy" for g in grants))
        self.assertFalse(
            [
                g
                for g in grants
                if g.resource.startswith("project/") and g.level != "access"
            ]
        )

    def test_the_owner_is_refused_a_change(self):
        owner = next(g for g in self.provider.read() if g.level == "owner")
        op = Op("remove", owner)

        self.assertIn(op, self.provider.guard([op], [owner]))

    def test_an_invitation_is_granted_then_revoked(self):
        grant = Grant("dokploy", THROWAWAY, "org", "member")

        self.provider.apply(Op("add", grant))
        self.assertIn(grant, self.provider.read())

        self.provider.apply(Op("remove", grant))
        self.assertNotIn(THROWAWAY, {g.account for g in self.provider.read()})
