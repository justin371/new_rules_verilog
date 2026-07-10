import tempfile
import threading
import unittest
import datetime
import os
import signal
import subprocess
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
        self.vcomper = None
        self.log_path = ""

    def _get_total_time_str(self):
        return "0:00:{:02d}".format(self.job_time)


class _RecordingRunner:
    started = threading.Event()

    def __init__(self, job, _manager):
        job.job_lib = self
        job.jobstatus = JobStatus.PASSED
        self.started.set()

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
    def post_run(self):
        raise RuntimeError("failed to collect results")


class _RunningProcess:
    pid = 123
    returncode = None

    def poll(self):
        return None


class JobManagerLaunchTest(unittest.TestCase):
    def test_bazel_tb_job_builds_runfiles_without_running_dummy_executable(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1, no_compile=False, no_bazel=False), log=log)
        vcomper = SimpleNamespace(job_dir="vcomp_dir", add_dependency=lambda _job: None)

        job = BazelTBJob(rcfg, "//pkg:tb", vcomper)

        self.assertEqual("bazel build //pkg:tb", job.main_cmdline)

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
        rcfg = SimpleNamespace(options=SimpleNamespace(timeout=1), log=log)
        job = Job(rcfg, "vcomp")
        job.job_dir = str(Path(tempfile.mkdtemp()) / "vcomp")
        manager = JobManager({"idle_print_seconds": 60, "quit_count": 1}, log)
        manager.job_lib_type = _FailingRunner

        try:
            manager.add_job(job)
            manager.wait()
            self.assertEqual(JobStatus.FAILED, job.jobstatus)
            self.assertIn(job, manager._done)
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
        runner._start_time = datetime.datetime.now() - datetime.timedelta(hours=1)
        runner._timed_out = False
        runner._term_deadline = None
        runner._kill_sent = False

        with mock.patch("lib.job_lib.os.getpgid", return_value=456, create=True), mock.patch(
            "lib.job_lib.os.killpg", create=True
        ) as killpg, mock.patch("lib.job_lib.signal.SIGKILL", 9, create=True):
            self.assertFalse(runner._check_for_done())
            runner._term_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
            self.assertFalse(runner._check_for_done())

        self.assertEqual(
            [mock.call(456, signal.SIGTERM), mock.call(456, 9)],
            killpg.call_args_list,
        )
        self.assertEqual(-signal.SIGTERM, runner.returncode)

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

    def test_coverage_imc_command_preserves_paths_with_spaces(self):
        log = _Logger()
        rcfg = SimpleNamespace(options=SimpleNamespace(coverage=True), log=log)
        job = SimpleNamespace(cov_work_dir="/tmp/path with spaces")
        failed = SimpleNamespace(returncode=1, stderr="failed")

        with mock.patch("lib.rv_utils.subprocess.run", return_value=failed) as run:
            rv_utils.get_coverage_data(rcfg, {"//pkg:sys_tb": job})

        run.assert_called_once_with(
            ["runmod", "xrun", "--", "imc", "-exec",
             os.path.join(job.cov_work_dir, "imc_report.tcl"), "-verbose"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_summary_leaves_max_job_time_blank_for_skipped_tests(self):
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


if __name__ == "__main__":
    unittest.main()
