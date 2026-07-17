import os
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
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
from lib import compile_cache
from lib.job_lib import JobCancelledError


def _replace_symlink_in_process(link_path, target_path, start, result_queue):
    start.wait(5.0)
    try:
        simmer.replace_symlink(link_path, target_path)
    except Exception as exc:
        result_queue.put(repr(exc))
    else:
        result_queue.put(None)


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

    def test_interrupted_run_cleans_backend_and_persists_failed_history(self):
        with tempfile.TemporaryDirectory() as project_dir:
            run = {
                "planned_tests": 1,
                "tests": [],
                "compile": [],
                "launch_failures": [],
            }
            rcfg = SimpleNamespace(
                proj_dir=project_dir,
                simmer_results_run=run,
                log=mock.Mock(),
            )
            simulator = mock.Mock()

            with mock.patch("simmer.simmer_results.save_run") as save_run:
                simmer.finalize_interrupted_run(rcfg, simulator, {"//tb:tb": object()})

            simulator.cleanup_shared_runtime_artifacts.assert_called_once()
            self.assertEqual("FAILED", run["status"])
            self.assertIsNotNone(run["finished_at"])
            save_run.assert_called_once_with(project_dir, run)

    def test_interrupted_history_persistence_failure_is_nonfatal(self):
        run = {
            "planned_tests": 1,
            "tests": [],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            log=mock.Mock(),
        )

        with mock.patch("simmer.simmer_results.save_run", side_effect=ValueError("invalid history")):
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {})

        self.assertEqual("FAILED", run["status"])
        rcfg.log.error.assert_called_once_with("Failed to write interrupted simmer results: %s", mock.ANY)

    def test_interrupted_run_skips_cleanup_until_every_job_stops(self):
        rcfg = SimpleNamespace(simmer_results_run=None, log=mock.Mock())
        simulator = mock.Mock()

        simmer.finalize_interrupted_run(rcfg, simulator, {}, cleanup_shared_runtime=False)

        simulator.cleanup_shared_runtime_artifacts.assert_not_called()
        rcfg.log.warning.assert_called_once()

    def test_interrupted_active_test_is_not_reported_as_skipped(self):
        run = {
            "planned_tests": 2,
            "tests": [],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            options=SimpleNamespace(waves=None),
            log=mock.Mock(),
        )
        vcomper = SimpleNamespace(
            name="tb",
            bazel_vcomp_target="//tb:tb",
            job_dir="/compile",
            log_path="/compile/cmp.log",
        )
        test_job = simmer.TestJob.__new__(simmer.TestJob)
        test_job.rcfg = rcfg
        test_job.vcomper = vcomper
        test_job.name = "test"
        test_job.target = "//tb:test"
        test_job.iteration = 1
        test_job.seed = 7
        test_job.job_dir = "/sim"
        test_job._log_path = "/sim/stdout.log"
        test_job.job_start_time = None
        test_job.job_stop_time = None
        test_job.error_message = None
        test_job._jobstatus = simmer.JobStatus.NOT_STARTED
        manager = SimpleNamespace(interrupted_jobs=(test_job, ))

        with mock.patch("simmer.simmer_results.save_run"):
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {}, jm=manager)

        self.assertEqual("INTERRUPTED", run["tests"][0]["status"])
        self.assertEqual(1, run["summary"]["interrupted"])
        self.assertEqual(1, run["summary"]["skipped"])

    def test_interrupted_compile_is_recorded_in_history(self):
        run = {
            "planned_tests": 1,
            "tests": [],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            log=mock.Mock(),
        )
        vcomp = simmer.VCompJob.__new__(simmer.VCompJob)
        vcomp.name = "tb"
        vcomp.bazel_vcomp_target = "//tb:tb"
        vcomp.job_dir = "/compile"
        vcomp.log_path = "/compile/cmp.log"
        vcomp.job_start_time = None
        vcomp.job_stop_time = None
        vcomp._jobstatus = simmer.JobStatus.NOT_STARTED
        manager = SimpleNamespace(interrupted_jobs=(vcomp, ))

        with mock.patch("simmer.simmer_results.save_run"):
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {"//tb:tb": vcomp}, jm=manager)

        self.assertEqual("INTERRUPTED", run["compile"][0]["status"])

    def test_interrupt_cleanup_temporarily_ignores_additional_sigint(self):
        previous_handler = object()
        with mock.patch("simmer.signal.signal", side_effect=[previous_handler, None]) as set_handler:
            with simmer._IgnoreAdditionalInterrupts():
                pass

        self.assertEqual(
            [
                mock.call(simmer.signal.SIGINT, simmer.signal.SIG_IGN),
                mock.call(simmer.signal.SIGINT, previous_handler),
            ],
            set_handler.call_args_list,
        )

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_shared_runtime_lock_serializes_identical_regressions(self):
        first = simmer.VCompJob.__new__(simmer.VCompJob)
        first._shared_runtime_locks = {}
        first._cancel_event = threading.Event()
        second = simmer.VCompJob.__new__(simmer.VCompJob)
        second._shared_runtime_locks = {}
        second._cancel_event = threading.Event()
        acquired = threading.Event()
        errors = []

        with tempfile.TemporaryDirectory() as root_dir, mock.patch("simmer.log", mock.Mock()):
            coverage_dir = os.path.join(root_dir, "tb__COV_WORK")
            first.acquire_shared_runtime_lock(coverage_dir)

            def acquire_second():
                try:
                    second.acquire_shared_runtime_lock(coverage_dir)
                    acquired.set()
                except Exception as exc:
                    errors.append(exc)

            waiter = threading.Thread(target=acquire_second)
            waiter.start()
            self.assertFalse(acquired.wait(0.1))
            first.release_shared_runtime_locks()
            self.assertTrue(acquired.wait(1.0))
            waiter.join(1.0)
            second.release_shared_runtime_locks()

        self.assertFalse(errors)

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_symlink_lock_wait_stops_after_cancellation(self):
        with tempfile.TemporaryDirectory() as result_dir:
            link_path = os.path.join(result_dir, ".last_sim")
            cancel_path = os.path.join(result_dir, "cancel")
            waiting_path = os.path.join(result_dir, "waiting")
            holder = compile_cache.CompileDirectoryLock(simmer._symlink_lock_path(link_path))
            self.assertTrue(holder.acquire(blocking=False))
            probe = ("import os, sys\n"
                     "from simmer import replace_symlink\n"
                     "from lib.job_lib import JobCancelledError\n"
                     "def cancel_check():\n"
                     "    open(sys.argv[3], 'a').close()\n"
                     "    if os.path.exists(sys.argv[2]):\n"
                     "        raise JobCancelledError('cancelled')\n"
                     "try:\n"
                     "    replace_symlink(sys.argv[1], 'target', cancel_check=cancel_check)\n"
                     "except JobCancelledError:\n"
                     "    sys.exit(3)\n")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(BIN_DIR), str(REPO_ROOT), environment.get("PYTHONPATH", "")])
            try:
                waiter = subprocess.Popen(
                    [sys.executable, "-c", probe, link_path, cancel_path, waiting_path],
                    env=environment,
                )
                deadline = time.monotonic() + 5.0
                while not os.path.exists(waiting_path) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(os.path.exists(waiting_path), "subprocess did not start waiting for the lock")
                self.assertIsNone(waiter.poll())
                Path(cancel_path).touch()
                self.assertEqual(3, waiter.wait(timeout=2.0))
            finally:
                holder.release()

            self.assertFalse(os.path.lexists(link_path))

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

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_compile_lock_wait_stops_after_cancellation(self):
        with tempfile.TemporaryDirectory() as result_dir:
            job_dir = os.path.join(result_dir, "tb__VCS_VCOMP")
            holder = compile_cache.CompileDirectoryLock(job_dir + ".compile.lock")
            self.assertTrue(holder.acquire(blocking=False))
            job = simmer.VCompJob.__new__(simmer.VCompJob)
            job.job_dir = job_dir
            job._compile_lock = None
            job._cancel_event = threading.Event()
            job.bazel_vcomp_target = "//tb:tb"
            job.name = "tb"
            job.simulator = SimpleNamespace(get_name=lambda: "vcs")
            errors = []
            previous_log = simmer.log
            simmer.log = mock.Mock()

            def acquire():
                try:
                    job._acquire_compile_lock()
                except Exception as exc:
                    errors.append(exc)

            waiter = threading.Thread(target=acquire)
            try:
                waiter.start()
                while job._compile_lock is None:
                    waiter.join(0.01)
                job.request_cancel()
                waiter.join(1.0)
            finally:
                holder.release()
                job._release_compile_lock()
                simmer.log = previous_log

            self.assertFalse(waiter.is_alive())
            self.assertEqual(1, len(errors))
            self.assertIsInstance(errors[0], JobCancelledError)

    @unittest.skipUnless(os.name == "posix", "POSIX atomic-symlink behavior")
    def test_shared_symlink_updates_are_atomic_and_cleanup_is_target_aware(self):
        with tempfile.TemporaryDirectory() as result_dir:
            link_path = os.path.join(result_dir, ".last_sim")
            context = multiprocessing.get_context("fork")
            start = context.Event()
            result_queue = context.Queue()
            processes = [
                context.Process(
                    target=_replace_symlink_in_process,
                    args=(link_path, target, start, result_queue),
                ) for target in ("first", "second")
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(5.0)

            self.assertEqual([0, 0], [process.exitcode for process in processes])
            self.assertEqual([None, None], sorted([result_queue.get(timeout=1.0) for _ in processes], key=str))
            final_target = os.readlink(link_path)
            self.assertIn(final_target, ("first", "second"))
            self.assertFalse(os.path.exists(link_path + ".lock"))
            self.assertTrue(os.path.isfile(simmer._symlink_lock_path(link_path)))
            other_target = "second" if final_target == "first" else "first"
            self.assertFalse(simmer.remove_symlink_if_target(link_path, other_target))
            self.assertTrue(os.path.lexists(link_path))
            self.assertTrue(simmer.remove_symlink_if_target(link_path, final_target))
            self.assertFalse(os.path.lexists(link_path))

            job_link_path = os.path.join(result_dir, "job", ".vcomp")
            os.makedirs(os.path.dirname(job_link_path))
            simmer.replace_symlink(job_link_path, "../compile")
            self.assertFalse(os.path.exists(job_link_path + ".lock"))
            self.assertTrue(os.path.isfile(simmer._symlink_lock_path(job_link_path)))


if __name__ == "__main__":
    unittest.main()
