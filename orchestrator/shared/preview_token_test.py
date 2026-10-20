import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config, preview_token  # noqa: E402


class PreviewToken(unittest.TestCase):
    def test_matches_the_shell_script_that_app_staging_uses(self):
        shell = subprocess.run([str(config.FACTORY_DIR / "infra/app-staging/preview-token.sh"), "demo-app"],
                               env={**os.environ, "PREVIEW_MASTER_SECRET": "x"}, capture_output=True, text=True)
        self.assertEqual(shell.stdout.strip(), preview_token.for_app("x", "demo-app"))


if __name__ == "__main__":
    unittest.main()
