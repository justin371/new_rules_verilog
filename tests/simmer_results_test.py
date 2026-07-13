import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from lib import simmer_results


class SimmerResultsTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name
        self.rcfg = SimpleNamespace(proj_dir=self.project_dir, regression_dir=self.project_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _completed_run(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        run["tests"] = [{
            "status": "PASSED",
            "cmp_log": "cmp.log",
            "stdout_log": "stdout.log",
            "waves": {
                "enabled": False,
            },
        }]
        simmer_results.finalize_run(run)
        return run

    def test_run_ids_are_unique(self):
        self.assertNotEqual(self._completed_run()["run_id"], self._completed_run()["run_id"])

    def test_concurrent_saves_preserve_both_runs(self):
        runs = [self._completed_run(), self._completed_run()]
        errors = []

        def save(run):
            try:
                simmer_results.save_run(self.project_dir, run)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=save, args=(run, )) for run in runs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([], errors)
        self.assertEqual(2, len(simmer_results.load_store(self.project_dir)["runs"]))

    def test_corrupt_history_is_reported_and_preserved(self):
        path = Path(simmer_results.results_path(self.project_dir))
        path.write_text("{broken", encoding="utf-8")

        self.assertIn("Unable to read simmer history", simmer_results.format_history(self.project_dir, 10))
        simmer_results.save_run(self.project_dir, self._completed_run())

        backups = list(path.parent.glob(path.name + ".corrupt.*"))
        self.assertEqual(1, len(backups))
        self.assertEqual("{broken", backups[0].read_text(encoding="utf-8"))
        self.assertEqual(1, len(json.loads(path.read_text(encoding="utf-8"))["runs"]))

    def test_backend_finalize_failure_takes_precedence_over_partial(self):
        run = self._completed_run()
        run["planned_tests"] = 2

        simmer_results.finalize_run(run, backend_finalize_failed=True)

        self.assertEqual("FAILED", run["status"])

    def test_backend_finalize_failure_with_no_tests_is_failed(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 0)

        simmer_results.finalize_run(run, backend_finalize_failed=True)

        self.assertEqual("FAILED", run["status"])

    def test_result_duration_is_simulator_time_and_retains_job_wall_time(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        test_job = SimpleNamespace(
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            vcomper=SimpleNamespace(
                name="tb",
                bazel_vcomp_target="//tb:tb",
                job_dir="compile",
                log_path="cmp.log",
            ),
            name="test",
            target="//tb:test",
            iteration=1,
            seed=7,
            jobstatus=SimpleNamespace(name="PASSED"),
            duration_s=19.8,
            simulation_duration_s=7,
            job_dir="sim",
            _log_path="stdout.log",
            error_message=None,
        )

        simmer_results.record_test_job(run, test_job)

        self.assertEqual(7, run["tests"][0]["duration_s"])
        self.assertEqual(19, run["tests"][0]["wall_duration_s"])

    def test_missing_simulator_duration_does_not_report_setup_time_as_simulation(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        test_job = SimpleNamespace(
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            vcomper=SimpleNamespace(
                name="tb",
                bazel_vcomp_target="//tb:tb",
                job_dir="compile",
                log_path="cmp.log",
            ),
            name="test",
            target="//tb:test",
            iteration=1,
            seed=None,
            jobstatus=SimpleNamespace(name="FAILED"),
            duration_s=19.8,
            simulation_duration_s=None,
            job_dir="sim",
            _log_path="stdout.log",
            error_message="setup failed",
        )

        simmer_results.record_test_job(run, test_job)

        self.assertIsNone(run["tests"][0]["duration_s"])
        self.assertEqual(19, run["tests"][0]["wall_duration_s"])

    def test_compile_failure_without_started_test_is_saved_and_shown(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        run["compile"] = [{
            "bench": "tb",
            "vcomp_target": "//tb:tb",
            "status": "FAILED",
            "compile_dir": "compile",
            "cmp_log": "cmp.log",
        }]
        simmer_results.finalize_run(run)

        simmer_results.save_run(self.project_dir, run)

        self.assertEqual("COMPILE_FAILED", run["status"])
        history = simmer_results.format_history(self.project_dir, 10, use_color=False)
        self.assertIn("COMPILE_FAILED", history)
        self.assertIn("compile: cmp.log", history)

    def test_multi_test_history_keeps_summary_and_one_representative_test(self):
        run = self._completed_run()
        run["planned_tests"] = 3
        run["tests"] = [
            {
                "status": "PASSED",
                "stdout_log": "pass.log"
            },
            {
                "status": "FAILED",
                "stdout_log": "fail.log"
            },
            {
                "status": "PASSED",
                "stdout_log": "pass2.log"
            },
        ]
        run["summary"] = {"passed": 2, "failed": 1, "skipped": 0, "total": 3}

        simmer_results.save_run(self.project_dir, run)

        stored = simmer_results.load_store(self.project_dir)["last_run"]
        self.assertEqual(run["summary"], stored["summary"])
        self.assertEqual(["fail.log"], [test["stdout_log"] for test in stored["tests"]])

    def test_record_test_job_updates_existing_iteration(self):
        run = simmer_results.create_run(["simmer"], self.rcfg, 1)
        test_job = SimpleNamespace(
            duration_s=1,
            error_message=None,
            iteration=2,
            job_dir="sim",
            jobstatus=SimpleNamespace(name="PASSED"),
            name="smoke",
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            seed=17,
            simulation_duration_s=1,
            target="//tests:smoke",
            vcomper=SimpleNamespace(
                bazel_vcomp_target="//tb:top",
                job_dir="compile",
                log_path="cmp.log",
                name="top",
            ),
            _log_path="stdout.log",
        )
        simmer_results.record_test_job(run, test_job)
        test_job.error_message = "post-processing failed"
        test_job.jobstatus = SimpleNamespace(name="FAILED")
        simmer_results.record_test_job(run, test_job)

        self.assertEqual(1, len(run["tests"]))
        self.assertEqual("FAILED", run["tests"][0]["status"])
        self.assertEqual("post-processing failed", run["tests"][0]["error_message"])


if __name__ == "__main__":
    unittest.main()
