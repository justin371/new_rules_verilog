import unittest
from pathlib import Path


class ExternalPythonDepsTest(unittest.TestCase):

    def test_bazel_packages_do_not_require_workspace_owned_pip_repo(self):
        workspace = Path(__file__).resolve().parents[1]
        paths = [
            workspace / "WORKSPACE",
            workspace / "bin" / "BUILD",
            workspace / "lib" / "BUILD",
            workspace / "lib" / "simulators" / "BUILD",
        ]

        for path in paths:
            contents = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("@pip_deps", contents)
                self.assertNotIn("pip_parse(", contents)


if __name__ == "__main__":
    unittest.main()
