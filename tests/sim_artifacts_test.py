from pathlib import Path
import tempfile
import unittest

from lib import sim_artifacts


class SimArtifactsTest(unittest.TestCase):

    def test_runfiles_path_is_stable_from_per_test_directory(self):
        root = "/tmp/build/tb.runfiles/__main__"
        path = root + "/external/vendor/ip.f"

        self.assertEqual("bazel_runfiles_main/external/vendor/ip.f", sim_artifacts.runfiles_path(path, root))
        self.assertEqual("/outside/ip.f", sim_artifacts.runfiles_path("/outside/ip.f", root))

    def test_find_bazel_executable_supports_main_and_external_workspace(self):
        project = Path(tempfile.mkdtemp())
        external = project / "bazel-bin/external/rules_verilog/bin/check_test"
        external.parent.mkdir(parents=True)
        external.touch()
        self.assertEqual(str(external), sim_artifacts.find_bazel_executable(project, "check_test"))

        local = project / "bazel-bin/bin/check_test"
        local.parent.mkdir(parents=True)
        local.touch()
        self.assertEqual(str(local), sim_artifacts.find_bazel_executable(project, "check_test"))

    def test_write_executable_script_sets_execute_bits(self):
        path = Path(tempfile.mkdtemp()) / "rerun.sh"
        sim_artifacts.write_executable_script(path, "#!/usr/bin/env bash\n")

        self.assertEqual("#!/usr/bin/env bash\n", path.read_text(encoding="utf-8"))
        self.assertTrue(path.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
