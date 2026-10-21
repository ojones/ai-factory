import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import http_client, run_stops, spend_budget  # noqa: E402


class BudgetAccounting(unittest.TestCase):
    def setUp(self):
        self.calls, self.spend = [], {}
        self._orig = http_client.request

        def fake(method, url, token=None, body=None, timeout=60):
            self.calls.append((method, body))
            if method == "POST":
                jwt = f"jwt{len(self.calls)}"
                self.spend[jwt] = 0.0
                return 200, {"token": jwt}
            return 200, {"spending_current": self.spend[url.split("jwtoken=")[1]]}
        http_client.request = fake

    def tearDown(self):
        http_client.request = self._orig

    def test_each_jwt_is_single_model_and_limited_to_what_is_left(self):
        bud = spend_budget.Budget("admin", 2.0, 100)
        j1 = bud.mint("m1")
        self.spend[j1] = 0.75
        self.assertAlmostEqual(bud.refresh(j1), 0.75)
        bud.mint("m2")
        post = [c[1] for c in self.calls if c[0] == "POST"]
        self.assertEqual([p["models"] for p in post], [["m1"], ["m2"]])
        self.assertEqual([p["spending_limit"] for p in post], [2.0, 1.25])

    def test_spend_sums_across_jwts_and_exhaustion_stops_minting(self):
        bud = spend_budget.Budget("admin", 1.0, 100)
        j1 = bud.mint("m1")
        self.spend[j1] = 0.6
        bud.refresh(j1)
        j2 = bud.mint("m2")
        self.spend[j2] = 0.45
        self.assertAlmostEqual(bud.refresh(j2), 1.05)
        with self.assertRaises(run_stops.BudgetExhausted):
            bud.mint("m1")


if __name__ == "__main__":
    unittest.main()
