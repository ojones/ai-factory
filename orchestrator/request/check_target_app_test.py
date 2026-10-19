import unittest

from request import check_target_app


class FactoryRepo(unittest.TestCase):
    def test_only_a_repo_this_factory_created_is_ours(self):
        self.assertTrue(check_target_app.is_factory_repo("Intake: o/ai-factory#12", "o/ai-factory"))
        for bad in ("Intake: o/other#12", "Intake: o/ai-factory#12 and more", "", None, "A personal project", "Intake: o/ai-factory#x"):
            self.assertFalse(check_target_app.is_factory_repo(bad, "o/ai-factory"), bad)


if __name__ == "__main__":
    unittest.main()
