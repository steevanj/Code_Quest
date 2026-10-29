import shutil
import tempfile

from django.test import SimpleTestCase, override_settings

from runner import sandbox

from .curriculum import MISSIONS, starting_files

SANDBOX = tempfile.mkdtemp(prefix="forge-test-")


@override_settings(SANDBOX_ROOT=SANDBOX)
class MissionVerificationTests(SimpleTestCase):
    """Run every mission's checks in the real sandbox against its reference solution."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SANDBOX, ignore_errors=True)
        super().tearDownClass()

    def test_reference_solutions_pass_and_starting_code_does_not(self):
        session = "test-session-001"
        for mission in MISSIONS:
            with self.subTest(mission=mission["id"]):
                migrated = sandbox.migrate(session, mission["solution"])
                self.assertTrue(migrated["ok"], migrated.get("error"))
                result = sandbox.run_checks(session, mission["solution"], mission["checks"])
                failures = [r for r in result.get("results", []) if not r["passed"]]
                self.assertTrue(result["ok"] and not failures, failures or result.get("error"))

                start = sandbox.run_checks(session, starting_files(mission["id"]), mission["checks"])
                self.assertFalse(all(r["passed"] for r in start.get("results", [])) and start["ok"],
                                 f"{mission['id']} passes before any work is done")

    def test_request_trace_has_lifecycle(self):
        session = "test-session-002"
        files = MISSIONS[6]["solution"]
        sandbox.migrate(session, files)
        sandbox.request(session, files, "POST", "/api/categories/", {"name": "Shoes", "slug": "shoes"})
        result = sandbox.request(session, files, "POST", "/api/products/",
                                 {"name": "Boot", "slug": "boot", "price": "10.00", "stock": 1, "category": 1})
        stages = [e["stage"] for e in result["trace"]]
        self.assertEqual(stages[:3], ["request", "url", "view"])
        self.assertIn("sql", stages)
        self.assertEqual(result["trace"][-1]["status"], 201)
        product = next(t for t in result["schema"]["tables"] if t["name"] == "store_product")
        self.assertEqual(product["count"], 1)
