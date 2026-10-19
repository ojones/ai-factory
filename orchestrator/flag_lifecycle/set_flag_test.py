import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from flag_lifecycle import set_flag


class Usage(unittest.TestCase):
    def test_bad_input_is_refused_before_anything_is_called(self):
        with mock.patch.object(set_flag.http_client, "request") as http, redirect_stderr(io.StringIO()):
            self.assertEqual(set_flag.main(["x", "app", "flag", "maybe"]), 2)
            self.assertEqual(set_flag.main(["x", "../app", "flag", "on"]), 2)
            self.assertEqual(set_flag.main(["x", "app"]), 2)
        http.assert_not_called()


class Setting(unittest.TestCase):
    def run_main(self, want, replies):
        calls = []

        def fake(method, url, token, body=None):
            calls.append((method, url.split("/features/")[-1], body))
            return replies.pop(0)
        with mock.patch.dict("os.environ", {"GROWTHBOOK_ADMIN_PAT": "t"}), mock.patch.object(set_flag.http_client, "request", fake), \
                mock.patch("builtins.print"), redirect_stderr(io.StringIO()):
            return set_flag.main(["x", "app", "flag", want]), calls

    def feature(self, enabled, rules=()):
        return 200, {"feature": {"environments": {"production": {"enabled": enabled, "rules": list(rules)}}}}

    def test_it_switches_production_and_reads_it_back_keeping_the_rules(self):
        code, calls = self.run_main("on", [self.feature(False, [{"r": 1}]), (200, {}), self.feature(True)])
        self.assertEqual(code, 0)
        self.assertEqual(calls[1][2], {"environments": {"production": {"enabled": True, "rules": [{"r": 1}]}}})

    def test_a_flag_that_does_not_exist_is_not_created(self):
        code, calls = self.run_main("off", [(404, {})])
        self.assertEqual((code, len(calls)), (1, 1))

    def test_a_read_back_that_disagrees_is_a_failure(self):
        self.assertEqual(self.run_main("off", [self.feature(True), (200, {}), self.feature(True)])[0], 1)


if __name__ == "__main__":
    unittest.main()
