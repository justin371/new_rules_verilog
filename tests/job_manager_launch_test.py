import tempfile
import threading
import unittest
import datetime
from pathlib import Path
from types import SimpleNamespace

from lib import rv_utils
from lib.job_lib import BazelTBJob, BazelTestCfgJob, Job, JobManager, JobStatus


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

        rv_utils.print_summary(rcfg, {"//pkg:sys_tb": vcomp}, [icfg], manager, trd)

        self.assertIn(("", "skipped_test", "", "", "1", "", "1", "", ""), trd)


if __name__ == "__main__":
    unittest.main()
