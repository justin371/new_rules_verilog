import tempfile
import threading
import unittest
import datetime
import os
import signal
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

        with mock.patch("lib.job_lib.os.getpgid", return_value=456,
                        create=True), mock.patch("lib.job_lib.os.killpg",
                                                 create=True) as killpg, mock.patch("lib.job_lib.signal.SIGKILL",
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

        rv_utils.print_summary(rcfg, {"//pkg:sys_tb": vcomp}, SimpleNamespace(exited_prematurely=False), [])

        simulation_summary = next(message for message in log.messages if message.startswith("Simulation Summary"))
        self.assertRegex(simulation_summary, r"\b1\s+0\s+0\s+1\b")

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
            category_total_cases={"smoke": {"total": 1, "tags": ["smoke"]}},
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
