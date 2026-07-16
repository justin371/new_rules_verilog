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

    def test_materialize_python_script_copies_source_into_job(self):
        root = Path(tempfile.mkdtemp())
        source = root / "external repo" / "check_test.py"
        source.parent.mkdir(parents=True)
        source.write_text("print('checked')\n", encoding="utf-8")
        destination = root / "simulation job" / "check_test.py"
        destination.parent.mkdir(parents=True)

        result = sim_artifacts.materialize_python_script(source, destination)

        self.assertEqual(str(destination), result)
        self.assertEqual("print('checked')\n", destination.read_text(encoding="utf-8"))
        self.assertTrue(destination.stat().st_mode & 0o111)

    def test_write_executable_script_sets_execute_bits(self):
        path = Path(tempfile.mkdtemp()) / "rerun.sh"
        sim_artifacts.write_executable_script(path, "#!/usr/bin/env bash\n")

        self.assertEqual("#!/usr/bin/env bash\n", path.read_text(encoding="utf-8"))
        self.assertTrue(path.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
