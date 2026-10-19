# Tests for the maintenance pass. Run: python3 -m unittest discover -p "*_test.py" orchestrator
import unittest

from maintenance import dependency_updates as m


def pr(n, title, ref, labels=()):
    return {"number": n, "title": title, "url": f"https://github.com/o/a/pull/{n}", "headRefName": ref, "labels": [{"name": l} for l in labels]}


NPM = pr(1, "Bump express from 5.2.1 to 5.3.0", "dependabot/npm_and_yarn/express-5.3.0")
DOCKER = pr(2, "Bump node from 22-alpine to 24-alpine", "dependabot/docker/node-24-alpine")
ACTIONS = pr(3, "Bump actions/checkout from 4 to 5", "dependabot/github_actions/actions/checkout-5")
SEC = pr(4, "Bump tar from 6.1.0 to 6.2.1", "dependabot/npm_and_yarn/tar-6.2.1", ["dependencies", "security"])


class Classify(unittest.TestCase):
    def test_ecosystem_comes_from_the_branch_name(self):
        self.assertEqual([m.ecosystem(p) for p in (NPM, DOCKER, ACTIONS)], ["npm", "docker", "actions"])
        self.assertEqual(m.ecosystem(pr(9, "x", "feature/x")), "other")

    def test_agents_get_npm_and_docker_and_only_hear_about_the_rest(self):
        applicable, reported = m.split_prs([NPM, DOCKER, ACTIONS, pr(9, "x", "feature/x")])
        self.assertEqual([p["number"] for p in applicable], [1, 2])
        self.assertEqual([p["number"] for p in reported], [3, 9])

    def test_security_pull_requests_are_recognised(self):
        self.assertTrue(m.is_security(SEC))
        self.assertFalse(m.is_security(NPM))


class Decide(unittest.TestCase):
    def test_the_same_set_gets_the_same_key_in_any_order(self):
        self.assertEqual(m.update_key([NPM, DOCKER]), m.update_key([DOCKER, NPM]))
        self.assertNotEqual(m.update_key([NPM]), m.update_key([NPM, DOCKER]))

    def test_files_once_per_set_and_only_when_nothing_is_open(self):
        key = m.update_key([NPM])
        self.assertTrue(m.should_file([NPM], key, [], []))
        self.assertFalse(m.should_file([], "", [], []))
        self.assertFalse(m.should_file([NPM], key, [f"a: dependency updates [maint {key}]"], []))
        self.assertFalse(m.should_file([NPM], key, [], [{"number": 1}]))


class Request(unittest.TestCase):
    def test_security_first_with_links_and_the_not_applied_note(self):
        text = m.maintenance_request("a", [NPM, SEC], [ACTIONS])
        self.assertLess(text.index("tar from 6.1.0"), text.index("express from 5.2.1"))
        self.assertIn("**security**", text)
        self.assertIn("pull/1", text)
        self.assertIn("actions/checkout", text)
        self.assertIn("no feature flag", text)

    def test_a_long_title_is_clipped(self):
        self.assertLessEqual(len(m.clean_title("x" * 500)), 160)


if __name__ == "__main__":
    unittest.main()
