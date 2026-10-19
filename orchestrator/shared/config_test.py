import unittest
from unittest import mock

from shared import config


class Config(unittest.TestCase):
    def test_it_reads_the_real_profiles_file_with_roles_and_limits(self):
        cfg = config.load()
        self.assertIn("roles", cfg)
        self.assertIn("cost_cap_usd_default", cfg["limits"])

    def test_limits_of_a_config_without_any_is_empty_not_an_error(self):
        self.assertEqual(config.limits({"roles": {}}), {})
        self.assertEqual(config.limits({"limits": None}), {})
        self.assertEqual(config.limits({"limits": {"a": 1}}), {"a": 1})

    def test_limits_with_no_argument_reads_the_profiles_file(self):
        with mock.patch.object(config, "load", return_value={"limits": {"x": 2}}):
            self.assertEqual(config.limits(), {"x": 2})


if __name__ == "__main__":
    unittest.main()
