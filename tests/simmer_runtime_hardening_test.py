import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from args_parser import parse_args
import simmer


class _FatalLog:

    def critical(self, message, *args):
        if args:
            message = message % args
        raise SystemExit(message)


class SimmerRuntimeHardeningTest(unittest.TestCase):

    def test_get_bazel_bin_fallback_runs_from_project_directory(self):
        completed = SimpleNamespace(returncode=0, stdout="/output/bazel-bin\n", stderr="")
        with mock.patch("simmer.os.path.isdir", return_value=False), \
             mock.patch("simmer.subprocess.run", return_value=completed) as run:
            self.assertEqual("/output/bazel-bin", simmer.get_bazel_bin("/repo"))

        run.assert_called_once_with(
            ["bazel", "info", "bazel-bin"],
            cwd="/repo",
            capture_output=True,
            text=True,
        )

    def test_scheduler_numeric_options_reject_invalid_values(self):
        for arguments in (
            ["--jobs", "0"],
            ["--quit-count", "0"],
            ["--idle-print-seconds", "-1"],
            ["--timeout", "-0.5"],
            ["--history", "0"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                parse_args(arguments)

        self.assertEqual(0, parse_args(["--timeout", "0"]).timeout)

    def test_history_persistence_failure_is_fatal(self):
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run={"run_id": "test"},
            log=_FatalLog(),
        )
        with mock.patch("simmer.simmer_results.save_run", side_effect=OSError("disk full")), \
             self.assertRaisesRegex(SystemExit, "Failed to write simmer results"):
            simmer.persist_simmer_results(rcfg)

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_live_run_directory_collision_gets_suffix_and_releases(self):
        with tempfile.TemporaryDirectory() as result_dir:
            rcfg = SimpleNamespace(regression_dir=result_dir)
            first = simmer.TestJob.__new__(simmer.TestJob)
            first.rcfg = rcfg
            first.log = mock.Mock()
            first._run_directory_lock = None
            second = simmer.TestJob.__new__(simmer.TestJob)
            second.rcfg = rcfg
            second.log = mock.Mock()
            second._run_directory_lock = None
            third = simmer.TestJob.__new__(simmer.TestJob)
            third.rcfg = rcfg
            third.log = mock.Mock()
            third._run_directory_lock = None

            first_name, _ = first._claim_run_directory("tb__VCS__test__7")
            second_name, _ = second._claim_run_directory("tb__VCS__test__7")
            self.assertEqual("tb__VCS__test__7", first_name)
            self.assertRegex(second_name, r"^tb__VCS__test__7__run_p\d+$")

            first._release_run_directory_lock()
            third_name, _ = third._claim_run_directory("tb__VCS__test__7")
            self.assertEqual("tb__VCS__test__7", third_name)

            second._release_run_directory_lock()
            third._release_run_directory_lock()


if __name__ == "__main__":
    unittest.main()
