import unittest

from action_platform.core.service_access import (
    Access,
    AccessError,
    Grant,
    Op,
    Person,
    spec,
)
from action_platform.testing.access import MemoryDirectory

from apx_dokploy import DokployPlugin
from apx_dokploy.access import DokployAccess
from tests.fake import FakeApi, FakeDokploy

ANA = Person("ana@acme.dev", "u-ana", "Ana", "owner", ("platform",))
BEN = Person("ben@acme.dev", "u-ben", "Ben", "developer", ("backend",))


class World(unittest.TestCase):
    def setUp(self):
        self.dokploy = FakeDokploy()
        api = self.dokploy.project_create({"name": "api"})
        self.dokploy.project_create({"name": "site"})
        self.dokploy.member("ana@acme.dev", "owner")
        self.dokploy.member("ben@acme.dev", "member", [api["projectId"]])
        self.provider = DokployAccess(FakeApi(self.dokploy))
        self.directory = MemoryDirectory([ANA, BEN])
        self.access = Access(self.directory, {"dokploy": self.provider})

    def bootstrapped(self):
        self.access.sync(apply=True)


class Reading(World):
    def test_members_roles_and_project_access(self):
        grants = {(g.account, g.resource, g.level) for g in self.provider.read()}

        self.assertEqual(
            grants,
            {
                ("ana@acme.dev", "org", "owner"),
                ("ben@acme.dev", "org", "member"),
                ("ben@acme.dev", "project/api", "access"),
            },
        )

    def test_admins_and_owners_get_no_project_grants(self):
        self.dokploy.members[0]["accessedProjects"] = ["p1"]

        resources = {(g.account, g.resource) for g in self.provider.read()}

        self.assertNotIn(("ana@acme.dev", "project/api"), resources)

    def test_first_sync_imports_and_changes_nothing(self):
        plan = self.access.sync(apply=True)

        self.assertTrue(plan.bootstrap)
        self.assertEqual(plan.changes, [])
        self.assertEqual(self.dokploy.writes(), [])
        self.assertEqual(self.access.sync().changes, [])

    def test_expired_invitations_are_not_access(self):
        self.dokploy.invitations = [
            {
                "id": "i1",
                "email": "late@acme.dev",
                "role": "member",
                "status": "pending",
                "expiresAt": "2020-01-01T00:00:00.000Z",
            },
            {
                "id": "i2",
                "email": "soon@acme.dev",
                "role": "member",
                "status": "pending",
                "expiresAt": "2999-01-01T00:00:00.000Z",
            },
            {
                "id": "i3",
                "email": "gone@acme.dev",
                "role": "member",
                "status": "canceled",
            },
        ]

        accounts = {g.account for g in self.provider.read()}

        self.assertNotIn("late@acme.dev", accounts)
        self.assertNotIn("gone@acme.dev", accounts)
        self.assertIn("soon@acme.dev", accounts)

    def test_a_refused_call_is_an_access_error(self):
        provider = DokployAccess(FakeApi(self.dokploy, key="s3cr3t"))

        with self.assertRaises(AccessError) as caught:
            provider.read()

        self.assertIn("dokploy: project.all answered 401", str(caught.exception))
        self.assertNotIn("s3cr3t", str(caught.exception))


class Changing(World):
    def test_admins_need_no_project_grants(self):
        self.bootstrapped()
        self.directory.mapping.roles["owner"] = [
            spec("dokploy", "project/site", "access")
        ]

        self.assertEqual(self.access.sync().changes, [])

    def test_project_access_keeps_the_other_permissions(self):
        self.dokploy.members[1]["canAccessToDocker"] = True

        self.provider.apply(
            Op("add", Grant("dokploy", "ben@acme.dev", "project/site", "access"))
        )

        sent = self.dokploy.writes()[0][2]
        self.assertEqual(sent["accessedProjects"], ["p1", "p2"])
        self.assertEqual(sent["accessedEnvironments"], ["p2-production"])
        self.assertTrue(sent["canAccessToDocker"])

    def test_revoking_project_access_closes_its_environments(self):
        self.provider.apply(
            Op("add", Grant("dokploy", "ben@acme.dev", "project/site", "access"))
        )
        self.provider.apply(
            Op("remove", Grant("dokploy", "ben@acme.dev", "project/site", "access"))
        )

        self.assertEqual(self.dokploy.members[1]["accessedProjects"], ["p1"])
        self.assertEqual(self.dokploy.members[1]["accessedEnvironments"], [])

    def test_project_access_needs_an_accepted_member(self):
        with self.assertRaises(AccessError):
            self.provider.apply(
                Op("add", Grant("dokploy", "new@acme.dev", "project/api", "access"))
            )

    def test_unknown_project_is_refused(self):
        with self.assertRaises(AccessError):
            self.provider.apply(
                Op("add", Grant("dokploy", "ben@acme.dev", "project/nope", "access"))
            )

    def test_adding_a_member_sends_one_invitation(self):
        self.dokploy.invitations = [
            {
                "id": "i9",
                "email": "late@acme.dev",
                "role": "member",
                "status": "pending",
            }
        ]

        self.provider.apply(
            Op("add", Grant("dokploy", "late@acme.dev", "org", "admin"))
        )

        self.assertEqual(
            [(i["email"], i["role"]) for i in self.dokploy.invitations],
            [("late@acme.dev", "admin")],
        )

    def test_role_change_goes_through_the_member(self):
        self.provider.apply(
            Op("change", Grant("dokploy", "ben@acme.dev", "org", "admin"), "member")
        )

        self.assertEqual(self.dokploy.members[1]["role"], "admin")

    def test_removing_a_pending_invitation_cancels_it(self):
        self.dokploy.invitations = [
            {
                "id": "i9",
                "email": "late@acme.dev",
                "role": "member",
                "status": "pending",
            }
        ]

        self.provider.apply(
            Op("remove", Grant("dokploy", "late@acme.dev", "org", "member"))
        )

        self.assertEqual(self.dokploy.invitations, [])

    def test_revoke_names_what_remains_through_a_team(self):
        self.bootstrapped()
        self.directory.mapping.teams["backend"] = [
            spec("dokploy", "project/api", "access")
        ]

        plan = self.access.revoke("ben@acme.dev", "dokploy", "project/api")

        self.assertIn("team:backend", plan.note)

    def test_offboard_deletes_the_member(self):
        self.bootstrapped()

        plan = self.access.offboard("ben@acme.dev", apply=True)

        self.assertTrue(all(c.status == "applied" for c in plan.changes))
        self.assertNotIn(
            "ben@acme.dev", [m["user"]["email"] for m in self.dokploy.members]
        )
        self.assertIn("user.remove", [c[1] for c in self.dokploy.writes()])

    def test_the_owner_is_never_changed(self):
        self.bootstrapped()

        plan = self.access.offboard("ana@acme.dev", apply=True)

        self.assertEqual({c.status for c in plan.changes}, {"refused"})
        self.assertEqual(self.dokploy.members[0]["role"], "owner")
        self.assertEqual(len(self.dokploy.members), 2)

    def test_a_grant_never_makes_an_owner(self):
        self.bootstrapped()

        plan = self.access.grant("ben@acme.dev", "dokploy", "org", "owner", apply=True)

        org = next(c for c in plan.changes if c.resource == "org")
        self.assertEqual(org.status, "refused")
        self.assertEqual(self.dokploy.members[1]["role"], "member")

    def test_leaving_the_organization_is_drift(self):
        self.bootstrapped()
        self.directory.members = [ANA]

        drift = {
            (c.account, c.action) for s in self.access.audit().services for c in s.drift
        }

        self.assertIn(("ben@acme.dev", "remove"), drift)


class Plugin(unittest.TestCase):
    class Options:
        def __init__(self, **values):
            self.values = values

        def get(self, key, default=None):
            return self.values.get(key, default)

    def test_without_a_url_there_is_no_access(self):
        self.assertIsNone(DokployPlugin().access(self.Options()))

    def test_without_a_key_the_error_names_it(self):
        with self.assertRaises(AccessError) as caught:
            DokployPlugin().access(self.Options(url="https://dokploy.test"))

        self.assertIn("api_key", str(caught.exception))

    def test_url_and_key_build_the_provider(self):
        provider = DokployPlugin().access(
            self.Options(url="https://dokploy.test/", api_key="k")
        )

        self.assertIsInstance(provider, DokployAccess)
        self.assertEqual(provider.api.url, "https://dokploy.test")

    def test_the_environment_is_not_read(self):
        from unittest import mock

        env = {"DOKPLOY_URL": "https://dokploy.test", "DOKPLOY_API_KEY": "k"}

        with mock.patch.dict("os.environ", env):
            self.assertIsNone(DokployPlugin().access(self.Options()))
