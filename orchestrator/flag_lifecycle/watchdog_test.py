import unittest
from unittest import mock

from flag_lifecycle import watchdog


class TripRules(unittest.TestCase):
    ok, bad = {"healthy": True, "errors": 0}, {"healthy": False, "errors": 0}

    def test_counts_only_error_level_json_lines(self):
        log = '{"level":"info"}\n{"level": "error","msg":"x"}\n{"level":"FATAL"}\nplain error text\n'
        self.assertEqual(watchdog.count_errors(log), 2)
        self.assertEqual(watchdog.count_errors(None), 0)

    def test_consecutive_health_failures_trip_it(self):
        self.assertIsNotNone(watchdog.watchdog_trip([self.ok, self.bad, self.bad, self.bad], 0, 3, 5))

    def test_failures_that_recover_do_not(self):
        self.assertIsNone(watchdog.watchdog_trip([self.bad, self.bad, self.ok, self.bad, self.bad], 0, 3, 5))

    def test_a_rise_in_errors_over_the_baseline_trips_it(self):
        self.assertIsNotNone(watchdog.watchdog_trip([{"healthy": True, "errors": 9}], 3, 3, 5))
        self.assertIsNone(watchdog.watchdog_trip([{"healthy": True, "errors": 7}], 3, 3, 5))

    def test_errors_that_were_already_there_do_not(self):
        self.assertIsNone(watchdog.watchdog_trip([{"healthy": True, "errors": 40}] * 4, 40, 3, 5))

    def test_no_samples_no_trip(self):
        self.assertIsNone(watchdog.watchdog_trip([], 0, 3, 5))


if __name__ == "__main__":
    unittest.main()


class Watching(unittest.TestCase):
    LIMITS = {"watchdog_minutes": 1, "watchdog_interval_seconds": 0, "watchdog_max_failures": 2, "watchdog_max_errors": 5}

    def watch(self, statuses, errors=lambda: 0, limits=None, keys=("app.feature.new",)):
        disabled = []
        health = iter(statuses)
        with mock.patch.object(watchdog.time, "sleep"):
            result = watchdog.watch(list(keys), limits or self.LIMITS, float("inf"), lambda k: disabled.append(list(k)) or [], errors, lambda: next(health))
        return result, disabled

    def test_two_failed_health_checks_in_a_row_switch_the_released_flags_off(self):
        (minutes, reason, still_on), disabled = self.watch([200, 500, 500])
        self.assertEqual((minutes, still_on, disabled), (1.0, [], [["app.feature.new"]]))
        self.assertIn("health check failed 2 times", reason)

    def test_a_rise_in_errors_over_the_baseline_trips_it(self):
        counts = iter([0, 9])
        (_, reason, _), disabled = self.watch([200], errors=lambda: next(counts))
        self.assertIn("error-level log lines rose from 0 to 9", reason)
        self.assertEqual(disabled, [["app.feature.new"]])

    def test_a_healthy_app_is_left_alone_until_the_time_is_up(self):
        with mock.patch.object(watchdog.time, "time", side_effect=[0, 0, 1, 2, 100]):
            with mock.patch.object(watchdog.time, "sleep"):
                disabled = []
                out = watchdog.watch(["k"], self.LIMITS, float("inf"), lambda k: disabled.append(k) or [], lambda: 0, lambda: 200)
        self.assertEqual((out, disabled), ((1.0, None, []), []))

    def test_zero_minutes_or_nothing_released_means_no_watch(self):
        self.assertEqual(watchdog.watch(["k"], {"watchdog_minutes": 0}, 0, None, None, None), (None, None, []))
        self.assertEqual(watchdog.watch([], self.LIMITS, 0, None, None, None), (None, None, []))

    def test_the_deadline_ends_the_watch_early(self):
        self.assertEqual(watchdog.watch(["k"], self.LIMITS, 0, None, lambda: 0, None), (1.0, None, []))


class Disabling(unittest.TestCase):
    def test_each_flag_is_switched_off_and_read_back_and_one_that_stays_on_is_reported(self):
        from flag_lifecycle.fake_growthbook import FakeGrowthBook
        on = {"environments": {"production": {"enabled": True, "rules": []}}}
        gb = FakeGrowthBook({"a.feature.x": dict(on), "a.feature.y": dict(on)})
        real = gb.__call__

        def stubborn(method, path, body=None):
            if method == "POST" and path.endswith("a.feature.y"):
                return 200, {}  # accepted, but nothing changed
            return real(method, path, body)
        self.assertEqual(watchdog.disable_flags(stubborn, ["a.feature.x", "a.feature.y"]), ["a.feature.y"])
        self.assertFalse(gb.production_enabled("a.feature.x"))
