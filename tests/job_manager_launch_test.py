import tempfile
import threading
import unittest
import datetime
import os
import signal
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lib import rv_utils
from lib.job_lib import BazelTBJob, BazelTestCfgJob, Job, JobManager, JobStatus, SubprocessJobRunner


class _Logger:

    def __getattr__(self, _):
        return lambda *args, **kwargs: None


class _SummaryLogger(_Logger):

    def __init__(self):
        self.messages = []

    def summary(self, message, *args):
        if args:
            message = message % args
        self.messages.append(message)


class _FakeTimedJob:

    def __init__(self, name, status, seconds=0):
        self.name = name
        self.jobstatus = status
        self.job_time = seconds
        self.simulation_duration_s = seconds
        self.vcomper = None
        self.log_path = ""

    def _get_job_time_str(self):
        return "0:00:{:02d}".format(self.job_time)


class _RecordingRunner:
    started = threading.Event()

    def __init__(self, job, _manager):
        job.job_lib = self
        job.jobstatus = JobStatus.PASSED
        self.started.set()

    def check_for_done(self):
        return True


class _PausableRunner:
    instances = {}

    def __init__(self, job, _manager):
        job.job_lib = self
        self.job = job
        self.finish = threading.Event()
        self.paused = threading.Event()
        self.resumed = threading.Event()
        self.__class__.instances[job.name] = self

    def check_for_done(self):
        if not self.finish.is_set():
            return False
        self.job.jobstatus = JobStatus.PASSED
        return True

    def pause(self):
        self.paused.set()
        return True

    def resume(self):
        self.resumed.set()
        return True


class _IncompleteCompletionRunner:

    def __init__(self, job, _manager):
        job.job_lib = self
        self.shutdown_incomplete = True

    def check_for_done(self):
        return True


class _FailingPreRunJob(Job):

    def pre_run(self):
        super().pre_run()
        raise SystemExit("missing simv")


class _FailingRunner:

    def __init__(self, _job, _manager):
        raise OSError("failed to launch")


class _FailingPostRunJob(Job):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded_post_run_failure = None

    def post_run(self):
        raise RuntimeError("failed to collect results")

    def post_run_failed(self, exc):
        self.recorded_post_run_failure = str(exc)


class _BlockingPreRunJob(Job):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pre_run_started = threading.Event()
        self.release_pre_run = threading.Event()

    def pre_run(self):
        self.pre_run_started.set()
        self.release_pre_run.wait()
        super().pre_run()


class _BlockingPostRunJob(Job):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.post_run_started = threading.Event()
        self.release_post_run = threading.Event()
        self.cancelled = threading.Event()

    def post_run(self):
        self.post_run_started.set()
        self.release_post_run.wait()
        super().post_run()

    def cancel(self):
        self.cancelled.set()


class _TermIgnoringProcess:

    def __init__(self):
        self.wait_calls = []
        self.kill_called = False
        self.returncode = None

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) == 1:
            raise subprocess.TimeoutExpired("job", timeout)
        self.returncode = -signal.SIGKILL
        return self.returncode

    def kill(self):
        self.kill_called = True


class _NeverReapedProcess:

    def __init__(self):
        self.wait_calls = []
        self.kill_called = False
        self.returncode = None

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        raise subprocess.TimeoutExpired("job", timeout)

    def kill(self):
        self.kill_called = True


class _BlockingLaunchRunner:
    started = threading.Event()
    release = threading.Event()
    killed = threading.Event()

    def __init__(self, job, _manager):
        job.job_lib = self
        self.started.set()
        self.release.wait()

    def check_for_done(self):
        return False

    def kill(self):
        self.killed.set()


class _IncompleteLaunchRunner(_BlockingLaunchRunner):

    def kill(self):
        super().kill()
        return False


class _CancelableJob(Job):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()


class _ExitedProcess:
    pid = 123
    returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class _RunningProcess:
    pid = 123
    returncode = None

    def poll(self):
        return None


class JobManagerLaunchTest(unittest.TestCase):

    def test_default_results_directory_uses_xdg_state_home(self):
        project_dir = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": state_dir, "SIMRESULTS": ""}, clear=False):
            result_dir = rv_utils.calc_simresults_location(project_dir)

        self.assertTrue(result_dir.startswith(os.path.join(state_dir, "simmer")))

    def test_bazel_tb_job_builds_runfiles_without_running_dummy_executable(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_compile=False, no_bazel=False), log=log)
        vcomper = SimpleNamespace(job_dir="vcomp_dir", add_dependency=lambda _job: None)

        job = BazelTBJob(rcfg, "//pkg:tb", vcomper)

        self.assertEqual("bazel build //pkg:tb", job.main_cmdline)

    def test_bazel_tb_job_batches_test_configs_in_initial_build(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_compile=False, no_bazel=False), log=log)
        vcomper = SimpleNamespace(job_dir="vcomp_dir", add_dependency=lambda _job: None)

        job = BazelTBJob(rcfg, "//pkg:tb", vcomper, additional_targets=["//pkg/tests:first", "//pkg/tests:second"])

        self.assertEqual("bazel build //pkg:tb //pkg/tests:first //pkg/tests:second", job.main_cmdline)

    def test_no_compile_still_builds_test_configs(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_compile=True, no_bazel=False), log=log)
        vcomper = SimpleNamespace(job_dir="vcomp_dir", add_dependency=lambda _job: None)

        job = BazelTBJob(rcfg, "//pkg:tb", vcomper, additional_targets=["//pkg/tests:first", "//pkg/tests:second"])

        self.assertEqual("bazel build //pkg/tests:first //pkg/tests:second", job.main_cmdline)

    def test_no_bazel_bypasses_bazel_build_jobs(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_compile=False, no_bazel=True), log=log)
        vcomper = SimpleNamespace(
            job_dir="vcomp_dir",
            _children=[],
            add_dependency=lambda _job: None,
            increase_priority=lambda _priority: None,
        )

        tb_job = BazelTBJob(rcfg, "//pkg:tb", vcomper)
        cfg_job = BazelTestCfgJob(rcfg, "//pkg/tests:test", vcomper)

        self.assertIn("--no-compile/--no-bazel", tb_job.main_cmdline)
        self.assertIn("--no-bazel", cfg_job.main_cmdline)

    def test_test_cfg_job_batches_targets_and_reads_each_dynamic_args_file(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_bazel=False), log=log, proj_dir="/repo")
        vcomper = SimpleNamespace(
            job_dir="vcomp_dir",
            _children=[],
            add_dependency=lambda _job: None,
            increase_priority=lambda _priority: None,
        )
        job = BazelTestCfgJob(rcfg, ["//pkg/tests:first", "//pkg/tests:second"], vcomper)

        self.assertEqual("bazel build //pkg/tests:first //pkg/tests:second", job.main_cmdline)
        with mock.patch("builtins.open", mock.mock_open(read_data="{'simulator': 'VCS'}")) as open_file:
            job.dynamic_args("//pkg/tests:second")
        open_file.assert_called_once_with(os.path.join("/repo", "bazel-bin", "pkg/tests", "second_dynamic_args.py"),
                                          'r')

    def test_prebuilt_test_cfg_job_skips_second_bazel_invocation(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_bazel=False), log=log)
        vcomper = SimpleNamespace(
            job_dir="vcomp_dir",
            _children=[],
            add_dependency=lambda _job: None,
            increase_priority=lambda _priority: None,
        )

        job = BazelTestCfgJob(rcfg, ["//pkg/tests:first", "//pkg/tests:second"], vcomper, prebuilt=True)

        self.assertNotIn("bazel build", job.main_cmdline)
        self.assertIn("initial Bazel build", job.main_cmdline)

    def test_add_job_wakes_idle_scheduler(self):
        log = _Logger()
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _RecordingRunner
        job = Job(SimpleNamespace(options=SimpleNamespace(timeout=1), log=log), "test")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "job")

        try:
            _RecordingRunner.started.clear()
            manager.add_job(job)
            self.assertTrue(_RecordingRunner.started.wait(1.0))
            manager.wait()
            self.assertIn(job, manager._done)
        finally:
            manager.stop()

        self.assertFalse(manager.exited_prematurely)

    def test_subprocess_runner_uses_thread_safe_new_session_launch(self):
        log = _Logger()
        job = Job(SimpleNamespace(options=SimpleNamespace(timeout=1, no_stdout=False), log=log), "test")
        job.job_dir = tempfile.mkdtemp()
        job.main_cmdline = "echo test"
        process = _ExitedProcess()

        with mock.patch("lib.job_lib.subprocess.Popen", return_value=process) as popen:
            SubprocessJobRunner(job, SimpleNamespace())

        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("preexec_fn", popen.call_args.kwargs)

    def test_wait_and_add_are_race_safe_while_pre_run_is_unlocked(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        first = _BlockingPreRunJob(rcfg, "first")
        first.job_dir = str(Path(tempfile.mkdtemp()) / "first")
        second = Job(rcfg, "second")
        second.job_dir = str(Path(tempfile.mkdtemp()) / "second")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 2}, log)
        manager.job_lib_type = _RecordingRunner
        wait_finished = threading.Event()
        add_finished = threading.Event()

        try:
            manager.add_job(first)
            self.assertTrue(first.pre_run_started.wait(1.0))

            waiter = threading.Thread(target=lambda: (manager.wait(), wait_finished.set()))
            adder = threading.Thread(target=lambda: (manager.add_job(second), add_finished.set()))
            waiter.start()
            adder.start()

            self.assertTrue(add_finished.wait(1.0), "add_job blocked behind pre_run")
            self.assertFalse(wait_finished.wait(0.05), "wait returned during the launch transition")
            with manager._condition:
                self.assertIn(first, manager._launching)

            first.release_pre_run.set()
            waiter.join(2.0)
            adder.join(2.0)
            self.assertTrue(wait_finished.is_set())
            self.assertEqual({first, second}, set(manager._done))
        finally:
            first.release_pre_run.set()
            manager.stop()

    def test_kill_during_launch_terminates_runner_and_releases_job_resources(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = _CancelableJob(rcfg, "launching")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "launching")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _BlockingLaunchRunner
        _BlockingLaunchRunner.started.clear()
        _BlockingLaunchRunner.release.clear()
        _BlockingLaunchRunner.killed.clear()

        manager.add_job(job)
        self.assertTrue(_BlockingLaunchRunner.started.wait(1.0))
        killer = threading.Thread(target=manager.kill)
        killer.start()
        self.assertTrue(killer.is_alive(), "kill did not wait for the in-flight launch")

        _BlockingLaunchRunner.release.set()
        killer.join(2.0)

        self.assertFalse(killer.is_alive())
        self.assertTrue(_BlockingLaunchRunner.killed.is_set())
        self.assertTrue(job.cancelled.is_set())
        self.assertFalse(manager._run_jobs_thread.is_alive())

    def test_incomplete_launch_shutdown_keeps_job_resources_locked(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = _CancelableJob(rcfg, "launching")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "launching")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _IncompleteLaunchRunner
        _IncompleteLaunchRunner.started.clear()
        _IncompleteLaunchRunner.release.clear()
        _IncompleteLaunchRunner.killed.clear()
        shutdown_result = []

        manager.add_job(job)
        self.assertTrue(_IncompleteLaunchRunner.started.wait(1.0))
        killer = threading.Thread(target=lambda: shutdown_result.append(manager.kill()))
        killer.start()
        _IncompleteLaunchRunner.release.set()
        killer.join(2.0)

        self.assertEqual([False], shutdown_result)
        self.assertTrue(_IncompleteLaunchRunner.killed.is_set())
        self.assertFalse(job.cancelled.is_set())

    def test_kill_waits_for_post_run_without_cancelling_finalizing_job(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = _BlockingPostRunJob(rcfg, "finalizing")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "finalizing")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _RecordingRunner
        shutdown_result = []

        try:
            manager.add_job(job)
            self.assertTrue(job.post_run_started.wait(1.0))
            with manager._condition:
                self.assertIn(job, manager._finalizing)

            killer = threading.Thread(target=lambda: shutdown_result.append(manager.kill()))
            killer.start()
            self.assertTrue(killer.is_alive(), "kill did not wait for post_run")
            self.assertFalse(job.cancel_requested)
            self.assertFalse(job.cancelled.is_set())
            self.assertEqual(JobStatus.PASSED, job.jobstatus)
            self.assertEqual((job, ), manager.interrupted_jobs)

            job.release_post_run.set()
            killer.join(2.0)
            self.assertFalse(killer.is_alive())
            self.assertEqual([True], shutdown_result)
            self.assertIn(job, manager._done)
            self.assertEqual((), manager.interrupted_jobs)
        finally:
            job.release_post_run.set()
            manager._run_jobs_thread.join(2.0)

    def test_completed_finalizing_job_is_not_reported_as_interrupted(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = _BlockingPostRunJob(rcfg, "finalizing")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "finalizing")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _RecordingRunner

        try:
            manager.add_job(job)
            self.assertTrue(job.post_run_started.wait(1.0))
            killer = threading.Thread(target=manager.kill)
            killer.start()
            job.release_post_run.set()
            killer.join(2.0)

            self.assertEqual(JobStatus.PASSED, job.jobstatus)
            self.assertEqual((), manager.interrupted_jobs)
        finally:
            job.release_post_run.set()
            manager._run_jobs_thread.join(2.0)

    def test_default_shutdown_wait_covers_process_group_escalation_budget(self):
        self.assertGreaterEqual(
            JobManager.SHUTDOWN_JOIN_SECONDS,
            SubprocessJobRunner.TERM_GRACE_SECONDS + 2 * SubprocessJobRunner.KILL_GRACE_SECONDS,
        )

    def test_pause_blocks_new_jobs_until_resume(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        first = Job(rcfg, "first")
        second = Job(rcfg, "second")
        first.job_dir = str(Path(tempfile.mkdtemp()) / "first")
        second.job_dir = str(Path(tempfile.mkdtemp()) / "second")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1, "active_job_limit": 1}, log)
        manager.job_lib_type = _PausableRunner
        _PausableRunner.instances = {}

        try:
            manager.add_job(first)
            manager.add_job(second)
            deadline = time.monotonic() + 2.0
            while "first" not in _PausableRunner.instances and time.monotonic() < deadline:
                time.sleep(0.01)
            first_runner = _PausableRunner.instances["first"]

            self.assertEqual(1, manager.pause())
            self.assertTrue(manager.paused)
            self.assertTrue(first_runner.paused.is_set())
            first_runner.finish.set()
            deadline = time.monotonic() + 2.0
            while first not in manager.status_snapshot()["done"] and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertNotIn("second", _PausableRunner.instances)

            self.assertEqual(0, manager.resume())
            deadline = time.monotonic() + 2.0
            while "second" not in _PausableRunner.instances and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn("second", _PausableRunner.instances)
            _PausableRunner.instances["second"].finish.set()
            manager.wait()
        finally:
            manager.stop()

    def test_incomplete_process_shutdown_skips_post_run_and_stops_scheduling(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = Job(rcfg, "unreaped")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "unreaped")
        job.post_run = mock.Mock()
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 2}, log)
        manager.job_lib_type = _IncompleteCompletionRunner

        try:
            manager.add_job(job)
            manager.wait()

            self.assertEqual(JobStatus.FAILED, job.jobstatus)
            self.assertTrue(manager.shutdown_incomplete)
            job.post_run.assert_not_called()
        finally:
            manager.stop()

    def test_kill_signals_active_jobs_concurrently(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.stop()
        first = Job(rcfg, "first")
        second = Job(rcfg, "second")
        first_started = threading.Event()
        release_first = threading.Event()
        second_signalled = threading.Event()

        def block_first():
            first_started.set()
            release_first.wait()

        first.job_lib = SimpleNamespace(kill=block_first)
        second.job_lib = SimpleNamespace(kill=second_signalled.set)
        with manager._condition:
            manager._active = [first, second]

        killer = threading.Thread(target=manager.kill)
        killer.start()
        self.assertTrue(first_started.wait(1.0))
        self.assertTrue(second_signalled.wait(1.0), "second kill waited behind the blocked first kill")
        release_first.set()
        killer.join(2.0)
        self.assertFalse(killer.is_alive())

    def test_kill_reports_incomplete_active_shutdown(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.stop()
        manager.ACTIVE_KILL_JOIN_SECONDS = 0.05
        job = _CancelableJob(rcfg, "blocked")
        release = threading.Event()
        finished = threading.Event()

        def block_kill():
            release.wait()
            finished.set()

        job.job_lib = SimpleNamespace(kill=block_kill)
        with manager._condition:
            manager._active = [job]

        self.assertFalse(manager.kill())
        self.assertEqual((job, ), manager.interrupted_jobs)
        self.assertFalse(job.cancelled.is_set())
        release.set()
        self.assertTrue(finished.wait(1.0))

    def test_kill_returns_bounded_when_pre_run_does_not_cooperate(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = _BlockingPreRunJob(rcfg, "blocked")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "blocked")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _RecordingRunner
        manager.SHUTDOWN_JOIN_SECONDS = 0.05
        self.assertTrue(manager._run_jobs_thread.daemon)

        try:
            manager.add_job(job)
            self.assertTrue(job.pre_run_started.wait(1.0))
            start = datetime.datetime.now()
            shutdown_complete = manager.kill()
            elapsed = (datetime.datetime.now() - start).total_seconds()
            self.assertLess(elapsed, 0.5)
            self.assertFalse(shutdown_complete)
            self.assertTrue(job.cancel_requested)
            self.assertEqual((job, ), manager.interrupted_jobs)
        finally:
            job.release_pre_run.set()
            manager._run_jobs_thread.join(2.0)

        self.assertFalse(manager._run_jobs_thread.is_alive())

    def test_pre_run_failure_fails_job_without_killing_scheduler(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        parent = _FailingPreRunJob(rcfg, "vcomp")
        parent.job_dir = str(Path(tempfile.mkdtemp()) / "vcomp")
        child = Job(rcfg, "sim")
        child.job_dir = str(Path(tempfile.mkdtemp()) / "sim")
        child.add_dependency(parent)
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)

        try:
            manager.add_job(parent)
            manager.add_job(child)
            manager.wait()

            self.assertEqual(JobStatus.FAILED, parent.jobstatus)
            self.assertEqual(JobStatus.SKIPPED, child.jobstatus)
            self.assertIn(parent, manager._done)
            self.assertIn(child, manager._skipped)
        finally:
            manager.stop()

    def test_runner_launch_failure_fails_job_without_killing_scheduler(self):
        log = _Logger()
        result_run = {"launch_failures": []}
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log, simmer_results_run=result_run)
        job = Job(rcfg, "vcomp")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "vcomp")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _FailingRunner

        try:
            manager.add_job(job)
            manager.wait()
            self.assertEqual(JobStatus.FAILED, job.jobstatus)
            self.assertIn(job, manager._done)
            self.assertEqual("failed to launch", result_run["launch_failures"][0]["error_message"])
        finally:
            manager.stop()

    def test_post_run_failure_marks_job_failed(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = _FailingPostRunJob(rcfg, "sim")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "sim")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _RecordingRunner

        try:
            manager.add_job(job)
            manager.wait()
            self.assertEqual(JobStatus.FAILED, job.jobstatus)
            self.assertEqual("failed to collect results", job.recorded_post_run_failure)
        finally:
            manager.stop()

    def test_timeout_escalates_from_sigterm_to_sigkill(self):
        job_dir = Path(tempfile.mkdtemp())
        job = SimpleNamespace(
            timeout=0.001,
            suppress_output=False,
            job_dir=str(job_dir),
            rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)),
        )
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = job
        runner.log = _Logger()
        runner._p = _RunningProcess()
        runner._process_group_id = 456
        runner._start_time = datetime.datetime.now() - datetime.timedelta(hours=1)
        runner._timed_out = False
        runner._orphaned_process_group = False
        runner._term_deadline = None
        runner._kill_deadline = None
        runner._kill_sent = False

        with mock.patch("lib.job_lib.os.killpg", create=True) as killpg, mock.patch("lib.job_lib.signal.SIGKILL",
                                                                                    9,
                                                                                    create=True):
            self.assertFalse(runner._check_for_done())
            runner._term_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
            self.assertFalse(runner._check_for_done())

        self.assertEqual(
            [mock.call(456, signal.SIGTERM), mock.call(456, 9)],
            killpg.call_args_list,
        )
        self.assertEqual(-signal.SIGTERM, runner.returncode)

    def test_timed_out_runner_kills_process_group_after_shell_exits(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner._p = _ExitedProcess()
        runner._process_group_id = 456
        runner._timed_out = True
        runner._orphaned_process_group = False
        runner._term_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
        runner._kill_deadline = None
        runner._kill_sent = False

        with mock.patch.object(runner, "_process_group_exists", side_effect=[True, False]), \
             mock.patch.object(runner, "_signal_process_group") as signal_group:
            self.assertFalse(runner._check_for_done())
            self.assertTrue(runner._check_for_done())

        signal_group.assert_called_once_with(signal.SIGKILL)

    def test_timed_out_runner_retains_ownership_until_process_exits(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner._p = _RunningProcess()
        runner._process_group_id = 456
        runner._timed_out = True
        runner._orphaned_process_group = False
        runner._term_deadline = datetime.datetime.now() - datetime.timedelta(seconds=2)
        runner._kill_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
        runner._kill_sent = True

        self.assertFalse(runner._check_for_done())
        self.assertEqual(-signal.SIGTERM, runner.returncode)
        runner._p = _ExitedProcess()
        runner._p.returncode = -signal.SIGKILL
        with mock.patch.object(runner, "_process_group_exists", return_value=False):
            self.assertTrue(runner._check_for_done())
        self.assertEqual(-signal.SIGKILL, runner.returncode)

    def test_timed_out_runner_stops_waiting_after_bounded_ownership_grace(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner._p = _RunningProcess()
        runner._process_group_id = 456
        runner._timed_out = True
        runner._orphaned_process_group = False
        runner._term_deadline = datetime.datetime.now() - datetime.timedelta(seconds=2)
        runner._kill_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
        runner._ownership_deadline = datetime.datetime.now() - datetime.timedelta(seconds=0.5)
        runner._kill_sent = True
        runner._kill_failure_reported = True

        self.assertTrue(runner._check_for_done())
        self.assertTrue(runner.shutdown_incomplete)

    def test_runner_pause_resume_signals_group_and_excludes_paused_time_from_timeout(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(timeout=1,
                                     suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner.done = False
        runner._p = _RunningProcess()
        runner._process_group_id = 456
        runner._timed_out = False
        runner._orphaned_process_group = False
        runner._kill_sent = False
        runner._kill_lock = threading.Lock()
        runner._paused = False
        runner._paused_at = None
        runner._pause_intervals = []
        runner._start_time = datetime.datetime.now()

        with mock.patch.object(runner, "_signal_process_group") as signal_group, \
             mock.patch.object(runner, "_signal_sidecar_process_groups") as signal_sidecars:
            self.assertTrue(runner.pause())
            runner._paused_at -= datetime.timedelta(seconds=5)
            self.assertFalse(runner._check_for_done())
            self.assertTrue(runner.resume())

        self.assertEqual([mock.call(signal.SIGSTOP), mock.call(signal.SIGCONT)], signal_group.call_args_list)
        self.assertEqual([mock.call(signal.SIGSTOP), mock.call(signal.SIGCONT)], signal_sidecars.call_args_list)
        self.assertGreaterEqual(runner._pause_intervals[0][1] - runner._pause_intervals[0][0],
                                datetime.timedelta(seconds=5))

    def test_pause_duration_only_counts_time_after_simulation_timeout_start(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        now = datetime.datetime.now()
        timeout_start = now - datetime.timedelta(seconds=3)
        runner._paused = False
        runner._paused_at = None
        runner._pause_intervals = [
            (now - datetime.timedelta(seconds=10), now - datetime.timedelta(seconds=5)),
            (now - datetime.timedelta(seconds=4), now - datetime.timedelta(seconds=2)),
        ]

        self.assertEqual(datetime.timedelta(seconds=1), runner._paused_duration_since(timeout_start, now))

    @unittest.skipUnless(os.name == "posix" and os.path.isdir("/proc"), "Linux process-group behavior")
    def test_pause_and_resume_signal_socket_sidecar_process_groups(self):
        sidecar_file = Path(tempfile.mkdtemp()) / "sidecars"
        main_process = subprocess.Popen([
            "bash",
            "-c",
            "set -m; bash -c 'while :; do sleep 1; done' & "
            "printf '%s\\n' \"$!\" > \"$1\"; set +m; while :; do sleep 1; done",
            "sidecar-parent",
            str(sidecar_file),
        ],
                                        start_new_session=True)
        deadline = time.monotonic() + 2
        while not sidecar_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(sidecar_file.exists())
        sidecar_pid = int(sidecar_file.read_text(encoding="ascii").strip())
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(sidecar_process_groups_path=str(sidecar_file))
        runner.log = _Logger()
        runner.done = False
        runner._p = main_process
        runner._process_group_id = main_process.pid
        runner._timed_out = False
        runner._kill_lock = threading.Lock()
        runner._paused = False
        runner._paused_at = None
        runner._pause_intervals = []

        def process_state(process_id):
            stat = Path("/proc/{}/stat".format(process_id)).read_text(encoding="ascii")
            return stat.rsplit(")", 1)[1].split()[0]

        def wait_for_state(process_id, stopped):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if (process_state(process_id) == "T") == stopped:
                    return
                time.sleep(0.01)
            self.fail("process {} did not reach expected stopped={} state".format(process_id, stopped))

        try:
            self.assertTrue(runner.pause())
            wait_for_state(main_process.pid, True)
            wait_for_state(sidecar_pid, True)
            self.assertTrue(runner.resume())
            wait_for_state(main_process.pid, False)
            wait_for_state(sidecar_pid, False)
        finally:
            for process_group in (main_process.pid, sidecar_pid):
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            main_process.wait(timeout=2)

    def test_sidecar_registry_rejects_process_groups_from_another_session(self):
        sidecar_file = Path(tempfile.mkdtemp()) / "sidecars"
        sidecar_file.write_text("789 earlier\n", encoding="ascii")
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(sidecar_process_groups_path=str(sidecar_file))
        runner._process_group_id = 456

        with mock.patch.object(runner, "_linux_process_identity", return_value=("S", 789, 456, "later")), \
             mock.patch("lib.job_lib.os.killpg") as kill_group:
            runner._signal_sidecar_process_groups(signal.SIGSTOP)

        kill_group.assert_not_called()

    def test_zombie_only_process_group_is_not_running(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner._process_group_id = 456

        with mock.patch.object(runner, "_process_group_has_live_member", return_value=False), \
             mock.patch("lib.job_lib.os.killpg") as kill_group:
            self.assertFalse(runner._process_group_exists())

        kill_group.assert_not_called()

    def test_successful_shell_with_background_processes_is_failed_and_reaped(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner._p = _ExitedProcess()
        runner._process_group_id = 456
        runner._timed_out = False
        runner._orphaned_process_group = False
        runner._term_deadline = None
        runner._kill_deadline = None
        runner._kill_sent = False

        with mock.patch.object(runner, "_process_group_exists", side_effect=[True, True, False]), \
             mock.patch.object(runner, "_signal_process_group") as signal_group:
            self.assertFalse(runner._check_for_done())
            runner._term_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
            self.assertFalse(runner._check_for_done())
            self.assertTrue(runner._check_for_done())

        self.assertEqual([mock.call(signal.SIGTERM), mock.call(signal.SIGKILL)], signal_group.call_args_list)
        self.assertEqual(-signal.SIGTERM, runner.returncode)

    def test_runner_exception_kills_and_reaps_process_group(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.done = False
        runner.job = SimpleNamespace(suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner._p = _ExitedProcess()
        runner._process_group_id = 456
        runner._check_for_done = mock.Mock(side_effect=RuntimeError("poll failed"))

        with mock.patch("lib.job_lib.os.killpg") as killpg, \
             mock.patch.object(runner, "_wait_for_process_group_exit", return_value=True), \
             mock.patch.object(runner._p, "wait", wraps=runner._p.wait) as wait:
            self.assertTrue(runner.check_for_done())

        killpg.assert_called_once_with(456, signal.SIGKILL)
        wait.assert_called_once_with(timeout=runner.KILL_GRACE_SECONDS)

    def test_runner_exception_uses_bounded_wait_when_direct_child_cannot_be_reaped(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.done = False
        runner.job = SimpleNamespace(suppress_output=False,
                                     rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)))
        runner.log = _Logger()
        runner._p = _NeverReapedProcess()
        runner._process_group_id = 456
        runner._check_for_done = mock.Mock(side_effect=RuntimeError("poll failed"))
        runner.KILL_GRACE_SECONDS = 0.01

        with mock.patch.object(runner, "_signal_process_group"), \
             mock.patch.object(runner, "_signal_sidecar_process_groups"), \
             mock.patch.object(runner, "_wait_for_process_group_exit", return_value=False):
            self.assertTrue(runner.check_for_done())

        self.assertEqual([0.01, 0.01], runner._p.wait_calls)
        self.assertTrue(runner._p.kill_called)
        self.assertTrue(runner.shutdown_incomplete)

    def test_test_timeout_waits_for_simulator_log_creation(self):
        job_dir = Path(tempfile.mkdtemp())
        simulator_log = job_dir / "stdout.log"
        job = SimpleNamespace(
            timeout=0.001,
            timeout_start_path=str(simulator_log),
            suppress_output=False,
            job_dir=str(job_dir),
            rcfg=SimpleNamespace(options=SimpleNamespace(no_stdout=False)),
        )
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = job
        runner.log = _Logger()
        runner._p = _RunningProcess()
        runner._start_time = datetime.datetime.now() - datetime.timedelta(hours=1)
        runner._timed_out = False
        runner._orphaned_process_group = False
        runner._term_deadline = None
        runner._kill_deadline = None
        runner._kill_sent = False
        runner._timeout_start = None
        runner._process_group_id = 456

        self.assertFalse(runner._check_for_done())
        self.assertFalse(runner._timed_out)

        simulator_log.touch()
        old_timestamp = (datetime.datetime.now() - datetime.timedelta(hours=1)).timestamp()
        os.utime(simulator_log, (old_timestamp, old_timestamp))
        with mock.patch("lib.job_lib.os.killpg", create=True) as killpg:
            self.assertFalse(runner._check_for_done())

        self.assertTrue(runner._timed_out)
        killpg.assert_called_once_with(456, signal.SIGTERM)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_explicit_kill_waits_and_escalates_the_process_group(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(name="stuck")
        runner.log = _Logger()
        runner._p = _TermIgnoringProcess()
        runner._process_group_id = 456
        runner._kill_sent = False
        runner._kill_lock = threading.Lock()
        runner.done = False
        runner.TERM_GRACE_SECONDS = 0.01
        runner.KILL_GRACE_SECONDS = 0.01

        with mock.patch.object(runner, "_signal_process_group") as signal_group, \
             mock.patch.object(runner, "_wait_for_process_group_exit", side_effect=[False, True]):
            self.assertTrue(runner.kill())

        self.assertEqual([mock.call(signal.SIGTERM), mock.call(signal.SIGKILL)], signal_group.call_args_list)
        self.assertEqual([0.01, 0.01], runner._p.wait_calls)
        self.assertTrue(runner.done)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_explicit_kill_uses_bounded_wait_when_direct_child_cannot_be_reaped(self):
        runner = SubprocessJobRunner.__new__(SubprocessJobRunner)
        runner.job = SimpleNamespace(name="stuck")
        runner.log = _Logger()
        runner._p = _NeverReapedProcess()
        runner._process_group_id = 456
        runner._kill_sent = False
        runner._kill_lock = threading.Lock()
        runner.shutdown_incomplete = False
        runner.done = False
        runner.TERM_GRACE_SECONDS = 0.01
        runner.KILL_GRACE_SECONDS = 0.01

        with mock.patch.object(runner, "_signal_process_group"), \
             mock.patch.object(runner, "_signal_sidecar_process_groups"), \
             mock.patch.object(runner, "_wait_for_process_group_exit", return_value=False):
            self.assertFalse(runner.kill())

        self.assertEqual([0.01, 0.01, 0.01], runner._p.wait_calls)
        self.assertTrue(runner._p.kill_called)
        self.assertTrue(runner.shutdown_incomplete)

    def test_simmer_profile_prints_phase_and_job_details(self):
        log = _SummaryLogger()
        job = Job(SimpleNamespace(options=SimpleNamespace(timeout=1), log=log), "profiled_job")
        job.job_dir = "job_dir"
        job.main_cmdline = "echo profiled"
        job.job_start_time = datetime.datetime(2026, 1, 1, 0, 0, 0)
        job.job_stop_time = datetime.datetime(2026, 1, 1, 0, 0, 2)
        job.jobstatus = JobStatus.PASSED

        rcfg = SimpleNamespace(
            options=SimpleNamespace(simmer_profile=True),
            profile_events=[(1.5, "test_discovery_match", "filter requested tests")],
            log=log,
        )
        manager = SimpleNamespace(_done=[job], _skipped=[])

        rv_utils.print_simmer_profile(rcfg, manager)

        output = "\n".join(log.messages)
        self.assertIn("Simmer Profile", output)
        self.assertIn("profiled_job", output)
        self.assertIn("cmd: echo profiled", output)
        self.assertIn("test_discovery_match", output)

    def test_summary_leaves_max_sim_time_blank_for_skipped_tests(self):
        log = _SummaryLogger()
        vcomp = SimpleNamespace(name="sys_tb", jobstatus=JobStatus.PASSED, log_path="cmp.log")
        skipped = _FakeTimedJob("skipped_test", JobStatus.SKIPPED)
        skipped.vcomper = vcomp
        icfg = SimpleNamespace(target=1, jobs=[skipped])
        rcfg = SimpleNamespace(
            all_vcomp={"//pkg:sys_tb": ([icfg], [skipped])},
            options=SimpleNamespace(no_run=False, report=False, nt=False),
            tests_to_tags={},
            log=log,
        )
        manager = SimpleNamespace(exited_prematurely=False)
        trd = []

        rv_utils.print_summary(rcfg, {"//pkg:sys_tb": vcomp}, manager, trd)

        self.assertIn(("", "skipped_test", "", "", "1", "", "1", "", ""), trd)

    def test_simulation_summary_does_not_count_compile_job(self):
        log = _SummaryLogger()
        vcomp = SimpleNamespace(name="sys_tb", jobstatus=JobStatus.PASSED, log_path="cmp.log")
        passed = _FakeTimedJob("smoke", JobStatus.PASSED, seconds=1)
        passed.vcomper = vcomp
        passed.target = "//pkg/tests:smoke"
        icfg = SimpleNamespace(target=1, jobs=[passed])
        rcfg = SimpleNamespace(
            all_vcomp={"//pkg:sys_tb": ([icfg], [passed])},
            options=SimpleNamespace(no_run=False, report=False, nt=False),
            tests_to_tags={},
            category_total_cases={},
            log=log,
        )

        trd = []
        rv_utils.print_summary(rcfg, {"//pkg:sys_tb": vcomp}, SimpleNamespace(exited_prematurely=False), trd)

        simulation_summary = next(message for message in log.messages if message.startswith("Simulation Summary"))
        self.assertRegex(simulation_summary, r"\b1\s+0\s+0\s+1\b")
        self.assertIn(("", "smoke", "0:00:01", "1", "", "", "1", "", "", "//pkg/tests:smoke"), trd)

    def test_category_stats_use_full_target_and_preserve_numeric_test_names(self):
        matching = _FakeTimedJob("reset_1", JobStatus.PASSED)
        matching.target = "//block_a/tests:reset_1"
        other = _FakeTimedJob("reset_1", JobStatus.FAILED)
        other.target = "//block_b/tests:reset_1"
        rcfg = SimpleNamespace(
            all_vcomp={
                "//block_a:tb": ([SimpleNamespace(jobs=[matching])], [matching]),
                "//block_b:tb": ([SimpleNamespace(jobs=[other])], [other]),
            },
            category_total_cases={"smoke": {
                "total": 1,
                "tags": ["smoke"]
            }},
            options=SimpleNamespace(no_run=False),
            tests_to_tags={
                matching.target: ["smoke"],
                other.target: ["nightly"],
            },
        )

        self.assertEqual({"smoke": {"total": 1, "executed": 1, "passed": 1}}, rv_utils.calc_category_stats(rcfg))

    def test_category_stats_do_not_count_skipped_test_as_executed(self):
        skipped = _FakeTimedJob("smoke", JobStatus.SKIPPED)
        skipped.target = "//block/tests:smoke"
        rcfg = SimpleNamespace(
            all_vcomp={"//block:tb": ([SimpleNamespace(jobs=[skipped])], [skipped])},
            category_total_cases={"smoke": {
                "total": 1,
                "tags": ["smoke"]
            }},
            options=SimpleNamespace(no_run=False),
            tests_to_tags={skipped.target: ["smoke"]},
        )

        self.assertEqual({"smoke": {"total": 1, "executed": 0, "passed": 0}}, rv_utils.calc_category_stats(rcfg))

    def test_missing_category_config_does_not_fabricate_totals(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            missing = os.path.join(temporary_dir, "missing.json")

            with self.assertRaises(FileNotFoundError):
                rv_utils.load_category_total_cases(missing)

    def test_report_header_tolerates_missing_tags_and_normalizes_git_suffix(self):
        rcfg = SimpleNamespace(
            current_time="20260711_120000_000001",
            options=SimpleNamespace(simulator="VCS"),
            proj_dir="/tmp/fallback_project",
        )

        def git_output(_cwd, *args):
            values = {
                ("rev-parse", "HEAD"): "deadbeef",
                ("remote", "get-url", "origin"): "git@github.com:example/digit.git",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("describe", "--tags", "--exact-match"): "",
                ("rev-parse", "--short", "HEAD"): "deadbee",
            }
            return values.get(args, "")

        with mock.patch("lib.rv_utils._git_output", side_effect=git_output):
            header = rv_utils.get_report_header(rcfg)

        self.assertEqual("digit", header["project_name"])
        self.assertEqual("", header["tag"])
        self.assertEqual("https://github.com/example/digit/commit/deadbeef", header["commit"])


if __name__ == "__main__":
    unittest.main()
