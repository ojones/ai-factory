import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from staging import verify_infrastructure as v  # noqa: E402

GREEN = [{"name": n, "status": "completed", "conclusion": "success"} for n in v.PIPELINE]


class FakeApp:
    def __init__(self, token="tok", runs=GREEN, secrets=(), health=200, cookie_for_anyone=False, connected=True, front_page=200):
        self.token, self.runs_ = token, runs
        self.secrets, self.health, self.cookie_for_anyone, self.connected, self.front_page = set(secrets), health, cookie_for_anyone, connected, front_page
        self.t = 0.0

    def http(self, method, url, headers):
        if url.endswith("/api/health"):
            return self.health, {}, json.dumps({"status": "ok"}) if self.health == 200 else ""
        cookie = "preview=x; Path=/" if (f"preview={self.token}" in url or (self.cookie_for_anyone and "preview=" in url)) else ""
        return self.front_page, {"set-cookie": cookie}, ""

    def deps(self, **kw):
        return v.Deps(self.http, lambda sha: self.runs_, lambda: self.secrets, lambda: self.connected, sleep=self.sleep, now=lambda: self.t)

    def sleep(self, s):
        self.t += s


class Checks(unittest.TestCase):
    def test_a_healthy_app_passes_every_check_in_order(self):
        app = FakeApp(secrets=v.STAGING_SECRETS)
        out = v.verify(app.deps(), "notes", "abc", "tok")
        self.assertEqual([r["check"] for r in out], list(v.CHECKS))
        self.assertTrue(all(r["ok"] for r in out), out)
        self.assertIn("Infrastructure verified", v.report(out))

    def test_each_failed_check_is_one_failure_event_for_the_staging_child_and_a_pass_is_none(self):
        app = FakeApp(secrets=v.STAGING_SECRETS, health=500)
        out = v.verify(app.deps(), "notes", "abc", "tok")
        events = v.failure_events("notes", "12", out)
        self.assertEqual({e["fingerprint"] for e in events}, {r["check"] for r in out if not r["ok"]})
        self.assertTrue(events and all(e["severity"] == "failure" and e["source"] == "staging" and e["story"] == 12 for e in events))
        healthy = v.verify(FakeApp(secrets=v.STAGING_SECRETS).deps(), "notes", "abc", "tok")
        self.assertEqual(v.failure_events("notes", "12", healthy), [])

    def test_a_pipeline_stage_that_failed_fails_ci_without_waiting_out_the_timeout(self):
        runs = [GREEN[0], dict(GREEN[1], conclusion="failure"), {"name": "Deploy to Fly", "status": "queued", "conclusion": None}]
        app = FakeApp(runs=runs)
        got = v.ci_green(app.deps(), "abc", 900)
        self.assertFalse(got["ok"])
        self.assertIn("Build: failure", got["detail"])
        self.assertEqual(app.t, 0.0)

    def test_a_pipeline_that_never_finishes_fails_after_the_timeout(self):
        app = FakeApp(runs=[{"name": "Test Gate", "status": "in_progress", "conclusion": None}])
        got = v.ci_green(app.deps(), "abc", 60)
        self.assertFalse(got["ok"])
        self.assertIn("did not finish within 1 minutes", got["detail"])

    def test_an_app_that_never_answers_health_fails(self):
        got = v.deploy_healthy(FakeApp(health=502).deps(), "notes", 20)
        self.assertFalse(got["ok"])

    def test_the_flag_service_check_needs_the_apps_sdk_connection(self):
        self.assertTrue(v.flag_service(FakeApp().deps(), "notes")["ok"])
        got = v.flag_service(FakeApp(connected=False).deps(), "notes")
        self.assertFalse(got["ok"])
        self.assertIn("no SDK connection named `notes`", got["detail"])

    def test_a_lookup_that_fails_is_a_failed_check(self):
        app = FakeApp()
        deps = v.Deps(app.http, lambda sha: [], lambda: set(), lambda: (_ for _ in ()).throw(OSError("GrowthBook is down")), sleep=app.sleep, now=lambda: app.t)
        self.assertFalse(v.flag_service(deps, "notes")["ok"])

    def test_a_front_page_that_does_not_answer_200_fails_the_smoke_check(self):
        self.assertFalse(v.smoke(FakeApp(front_page=503).deps(), "notes")["ok"])
        self.assertTrue(v.smoke(FakeApp().deps(), "notes")["ok"])

    def test_the_preview_cookie_goes_to_the_right_token_only(self):
        self.assertTrue(v.preview_token_path(FakeApp().deps(), "notes", "tok")["ok"])
        self.assertFalse(v.preview_token_path(FakeApp(token="other").deps(), "notes", "tok")["ok"])
        self.assertFalse(v.preview_token_path(FakeApp(cookie_for_anyone=True).deps(), "notes", "tok")["ok"])

    def test_only_the_secrets_staging_sets_must_be_present_and_the_declared_ones_are_not_looked_at(self):
        self.assertTrue(v.secrets_present(FakeApp(secrets=v.STAGING_SECRETS).deps())["ok"])
        got = v.secrets_present(FakeApp(secrets=("FLY_API_TOKEN",)).deps())
        self.assertFalse(got["ok"])
        self.assertIn("GROWTHBOOK_CLIENT_KEY", got["detail"])
        self.assertNotIn("WEATHER_API_KEY", got["detail"])

    def test_a_missing_staging_secret_is_a_failure_event(self):
        out = [v.secrets_present(FakeApp(secrets=("FLY_API_TOKEN",)).deps())]
        self.assertEqual([e["fingerprint"] for e in v.failure_events("notes", "12", out)], ["secrets_present"])

    def test_one_failure_does_not_hide_the_rest_and_a_crashing_check_is_a_failed_check(self):
        app = FakeApp()
        deps = app.deps()
        deps.secret_names = lambda: (_ for _ in ()).throw(RuntimeError("gh is down"))
        out = v.verify(deps, "notes", "abc", "tok")
        self.assertEqual(len(out), 6)
        failed = [r for r in out if not r["ok"]]
        self.assertEqual([r["check"] for r in failed], ["secrets_present"])
        self.assertIn("RuntimeError", failed[0]["detail"])
        self.assertIn("FAILED", v.report(out))


class ConnectionPaging(unittest.TestCase):
    def probes(self, pages):
        probes = v.LiveProbes({"FACTORY_PAT": "p", "GROWTHBOOK_ADMIN_PAT": "a"}, "o/app", "notes")
        probes.connections_page = mock.Mock(side_effect=pages)
        return probes

    def test_a_connection_past_the_first_page_is_found(self):
        probes = self.probes([{"connections": [{"name": "other"}], "hasMore": True, "nextOffset": 100},
                              {"connections": [{"name": "notes"}], "hasMore": False}])
        self.assertTrue(probes.flag_connection())
        self.assertEqual(probes.connections_page.call_args.args, (100,))

    def test_no_match_on_the_last_page_is_false(self):
        self.assertFalse(self.probes([{"connections": [{"name": "other"}], "hasMore": False}]).flag_connection())

    def test_a_page_that_promises_more_without_an_offset_stops(self):
        probes = self.probes([{"connections": [], "hasMore": True}])
        self.assertFalse(probes.flag_connection())
        self.assertEqual(probes.connections_page.call_count, 1)


if __name__ == "__main__":
    unittest.main()
