import subprocess
import sys
import unittest

SIMMER = sys.argv.pop(1)


class SimmerEntrypointTest(unittest.TestCase):

    def test_help_runs_from_bazel_launcher(self):
        result = subprocess.run(
            [SIMMER, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("usage: simmer", result.stdout)
        self.assertIn("--simulator {VCS,XRUN}", result.stdout)


if __name__ == "__main__":
    unittest.main()
