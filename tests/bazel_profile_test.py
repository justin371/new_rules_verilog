import json
import os
import tempfile
import unittest

from lib import bazel_profile


class BazelProfileTest(unittest.TestCase):
    def test_repository_timings_aggregate_real_repository_events(self):
        profile = {
            "traceEvents": [
                {"ph": "X", "cat": "skyframe", "name": "BazelRepositoryModule", "dur": 9_000_000},
                {"ph": "X", "cat": "repository", "name": "Repository rule @@rules_python", "dur": 2_000_000},
                {"ph": "X", "cat": "action", "name": "fetch external/pip_deps/wheel", "dur": 500_000},
                {"ph": "X", "cat": "repository", "name": "fetch", "dur": 250_000, "args": {"repository": "rules_python"}},
                {"ph": "i", "cat": "repository", "name": "Repository rule @ignored", "dur": 4_000_000},
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as profile_file:
            json.dump(profile, profile_file)
            profile_path = profile_file.name

        try:
            self.assertEqual(
                [(2.25, "rules_python", 2), (0.5, "pip_deps", 1)],
                bazel_profile.repository_timings(profile_path),
            )
        finally:
            os.remove(profile_path)


if __name__ == "__main__":
    unittest.main()
