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

    def test_vso_failure_takes_precedence_over_partial(self):
        run = self._completed_run()
        run["planned_tests"] = 2

        simmer_results.finalize_run(run, vso_finalize_merge_failed=True)

        self.assertEqual("FAILED", run["status"])
        self.assertEqual(1, run["summary"]["skipped"])


if __name__ == "__main__":
    unittest.main()
