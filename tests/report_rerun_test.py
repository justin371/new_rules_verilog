import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lib.regression_report import RegressionReport, coverage_artifact_lock, create_template_environment
from lib.report_rerun import _run_failed_test, _updated_results, run_report_rerun
from lib.simulators.vcs import merge_report_rerun_coverage


class _Log:

    def error(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


class _RenderFailure(Exception):
    pass


class ReportRerunTest(unittest.TestCase):

    def _report_environment(self):
        runfiles_root = Path(os.environ["TEST_SRCDIR"]) / os.environ.get("TEST_WORKSPACE", "__main__")
        return create_template_environment(runfiles_root / "bin/templates")

    def _coverage_revisions(self, coverage_root):
        return sorted(path.name for path in coverage_root.iterdir() if path.name != ".locks")

    def _create_rerun_fixture(self, root):
        project_dir = root / "project"
        regression_dir = root / "results"
        webroot_dir = root / "web"
        project_dir.mkdir()

        baseline = regression_dir / "report_coverage" / "original" / "bench" / "baseline.vdb"
        baseline.mkdir(parents=True)
        rerun_script = regression_dir / "failed test" / "rerun.sh"
        rerun_script.parent.mkdir(parents=True)
        rerun_script.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$@\" > {}\n"
            "printf '%s\\n' \"$SIMMER_REPORT_RERUN_DIR_SUFFIX\" > {}\n"
            "mkdir -p \"$SIMMER_REPORT_RERUN_COVERAGE_DIR/snps/coverage/db/testdata/test\"\n"
            "printf 'coverage\\n' > \"$SIMMER_REPORT_RERUN_COVERAGE_DIR/snps/coverage/db/testdata/test/test.info\"\n".
            format(
                shlex.quote(str(rerun_script.parent / "args.txt")),
                shlex.quote(str(rerun_script.parent / "suffix.txt")),
            ),
            encoding="utf-8",
        )
        rerun_script.chmod(0o755)

        urg = root / "fake urg.sh"
        urg.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "dbname=''\n"
            "report=''\n"
            "while (( $# )); do\n"
            "  case $1 in\n"
            "    -dir) test -d \"$2\"; test -f \"$3/snps/coverage/db/testdata/test/test.info\"; shift 3 ;;\n"
            "    -dbname) dbname=$2; shift 2 ;;\n"
            "    -report) report=$2; shift 2 ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            "mkdir -p \"$dbname\" \"$report\"\n"
            "printf '%s\\n' 'SCORE LINE COND TOGGLE FSM BRANCH ASSERT GROUP' "
            "'90 90 90 90 90 90 90 90' > \"$report/dashboard.txt\"\n",
            encoding="utf-8",
        )
        urg.chmod(0o755)

        manifest_path = root / "original.rerun.json"
        manifest_path.write_text(
            json.dumps({
                "schema_version":
                1,
                "webroot_dir":
                str(webroot_dir),
                "project_dir":
                str(project_dir),
                "regression_dir":
                str(regression_dir),
                "header": {
                    "branch": "main",
                    "commit": "",
                    "coverage_enabled": True,
                    "project_name": "project",
                    "revision": "abc",
                    "simulator": "VCS",
                    "tag": "",
                    "time": "20260719_120000_000001",
                    "username": "user",
                },
                "trd": [
                    ["bench", "vcomp", "", "1", "", "", "1", "", ""],
                    ["", "test", "0:00:01", "", "", "1", "1", "", "", "//unit:test"],
                ],
                "category_stats": {},
                "coverage": {
                    "artifact_dir": str(baseline.parent),
                    "baseline_db": str(baseline),
                    "urg_argv": [str(urg)],
                    "urg_parallel": False,
                    "urg_show_tests": False,
                    "metrics": {
                        "total": "80%"
                    },
                },
                "failed_tests": [{
                    "bench": "bench",
                    "test": "test",
                    "target": "//unit:test",
                    "seed": 42,
                    "iteration": 2,
                    "rerun_script": str(rerun_script),
                }],
            }),
            encoding="utf-8",
        )
        return {
            "baseline": baseline,
            "coverage_root": regression_dir / "report_coverage",
            "manifest": manifest_path,
            "regression_dir": regression_dir,
            "rerun_script": rerun_script,
            "webroot_dir": webroot_dir,
        }

    def test_successful_rerun_adds_coverage_and_creates_revision_report(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            fixture = self._create_rerun_fixture(Path(temporary_dir))

            def merge_while_baseline_locked(coverage, urg_argv, baseline_db, supplements, artifact_dir, logger):
                with coverage_artifact_lock(fixture["regression_dir"], "original", shared=False,
                                            blocking=False) as acquired:
                    self.assertFalse(acquired)
                return merge_report_rerun_coverage(coverage, urg_argv, baseline_db, supplements, artifact_dir, logger)

            with mock.patch("lib.report_rerun.merge_report_rerun_coverage",
                            side_effect=merge_while_baseline_locked), mock.patch.dict(
                                os.environ, {"SIMMER_BIN": "/bin/true"}):
                status = run_report_rerun(fixture["manifest"], self._report_environment(), _Log())

            self.assertEqual(0, status)
            bench_path = fixture["webroot_dir"] / "regression_report" / "project" / "bench"
            regressions = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            revision_time = next(iter(regressions))
            summary = regressions[revision_time]
            self.assertEqual(1, summary["passed"])
            self.assertEqual(0, summary["failed"])
            self.assertEqual(90.0, summary["cov_total"])
            self.assertEqual("20260719_120000_000001", summary["revision_of"])
            self.assertEqual("--no-report\n", (fixture["rerun_script"].parent / "args.txt").read_text(encoding="utf-8"))
            self.assertIn("_i1_report_rerun_",
                          (fixture["rerun_script"].parent / "suffix.txt").read_text(encoding="utf-8"))
            self.assertFalse((bench_path / "{}.rerun.json".format(revision_time)).exists())
            self.assertTrue(
                (fixture["regression_dir"] / "report_coverage" / revision_time / "bench" / "baseline.vdb").is_dir())
            self.assertTrue(fixture["baseline"].is_dir())

    def test_coverage_merge_timeout_discards_revision_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            fixture = self._create_rerun_fixture(Path(temporary_dir))
            timeout = subprocess.TimeoutExpired(["urg"], 1)
            with mock.patch("lib.report_rerun.merge_report_rerun_coverage", side_effect=timeout):
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_report_rerun(fixture["manifest"], self._report_environment(), _Log())

            self.assertEqual(["original"], self._coverage_revisions(fixture["coverage_root"]))
            self.assertTrue(fixture["baseline"].is_dir())

    def test_process_termination_discards_unpublished_revision_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            fixture = self._create_rerun_fixture(Path(temporary_dir))
            with mock.patch("lib.report_rerun.run_bounded_process", side_effect=SystemExit(143)):
                with self.assertRaisesRegex(SystemExit, "143"):
                    run_report_rerun(fixture["manifest"], self._report_environment(), _Log())

            self.assertEqual(["original"], self._coverage_revisions(fixture["coverage_root"]))
            self.assertTrue(fixture["baseline"].is_dir())

    def test_coverage_merge_requires_revised_vdb_before_removing_supplements(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            root = Path(temporary_dir)
            artifact_dir = root / "revision" / "bench"
            baseline = root / "original" / "baseline.vdb"
            supplement = artifact_dir / "supplements" / "smoke.vdb"
            dashboard = artifact_dir / "urg_report" / "dashboard.txt"
            baseline.mkdir(parents=True)
            supplement.mkdir(parents=True)
            dashboard.parent.mkdir(parents=True)
            dashboard.write_text(
                "SCORE LINE COND TOGGLE FSM BRANCH ASSERT GROUP\n"
                "90 90 90 90 90 90 90 90\n",
                encoding="utf-8",
            )
            completed = SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch("lib.simulators.vcs.run_bounded_process", return_value=completed), \
                 self.assertRaisesRegex(RuntimeError, "did not produce baseline.vdb"):
                merge_report_rerun_coverage({}, ["urg"], baseline, [supplement], artifact_dir, _Log())

            self.assertTrue(baseline.is_dir())
            self.assertTrue(supplement.is_dir())

    def test_malformed_result_count_is_rejected_before_rerun(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            fixture = self._create_rerun_fixture(Path(temporary_dir))
            manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
            manifest["trd"][1][3] = "not-a-number"
            fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "report row counts"):
                run_report_rerun(fixture["manifest"], self._report_environment(), _Log())
            self.assertEqual(["original"], self._coverage_revisions(fixture["coverage_root"]))

    def test_report_publication_failure_discards_revision_artifacts(self):
        for failure in (_RenderFailure("report render failed"), OSError("report write failed"),
                        KeyboardInterrupt("report interrupted"), SystemExit("report terminated")):
            with self.subTest(failure=type(failure).__name__), \
                 tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
                fixture = self._create_rerun_fixture(Path(temporary_dir))
                with mock.patch("lib.report_rerun.RegressionReport.run", side_effect=failure):
                    with self.assertRaisesRegex(type(failure), str(failure)):
                        run_report_rerun(fixture["manifest"], self._report_environment(), _Log())
                self.assertEqual(["original"], self._coverage_revisions(fixture["coverage_root"]))
                self.assertTrue(fixture["baseline"].is_dir())

    def test_late_report_publication_failure_rolls_back_revision(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            fixture = self._create_rerun_fixture(Path(temporary_dir))
            environment = self._report_environment()
            manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
            existing_header = dict(manifest["header"], time="20260718_120000_000001")
            existing_report = RegressionReport(SimpleNamespace(log=_Log()), environment, str(fixture["webroot_dir"]))
            existing_report.run(existing_header, manifest["trd"], {"bench": manifest["coverage"]["metrics"]}, {})
            report_root = fixture["webroot_dir"] / "regression_report"
            files_before = {
                path.relative_to(report_root): path.read_bytes()
                for path in report_root.rglob("*") if path.is_file() and ".locks" not in path.parts
            }

            with mock.patch("lib.report_rerun.RegressionReport.render_home_page",
                            side_effect=_RenderFailure("home render failed")):
                with self.assertRaisesRegex(_RenderFailure, "home render failed"):
                    run_report_rerun(fixture["manifest"], environment, _Log())

            self.assertEqual(["original"], self._coverage_revisions(fixture["coverage_root"]))
            files_after = {
                path.relative_to(report_root): path.read_bytes()
                for path in report_root.rglob("*") if path.is_file() and ".locks" not in path.parts
            }
            self.assertEqual(files_before, files_after)
            self.assertTrue(fixture["baseline"].is_dir())

    def test_post_publication_interrupt_keeps_report_coverage(self):
        for maintenance_method in ("_cleanup_committed_history", "_prune_run_launchers"):
            with self.subTest(maintenance_method=maintenance_method), \
                 tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
                fixture = self._create_rerun_fixture(Path(temporary_dir))
                with mock.patch("lib.report_rerun.RegressionReport.{}".format(maintenance_method),
                                side_effect=KeyboardInterrupt("maintenance interrupted")):
                    with self.assertRaisesRegex(KeyboardInterrupt, "maintenance interrupted"):
                        run_report_rerun(fixture["manifest"], self._report_environment(), _Log())

                bench_path = fixture["webroot_dir"] / "regression_report" / "project" / "bench"
                regressions = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
                revision_time = next(iter(regressions))
                self.assertTrue(
                    (fixture["regression_dir"] / "report_coverage" / revision_time / "bench" / "baseline.vdb").is_dir())

    def test_coverage_root_is_not_accepted_as_a_baseline(self):
        with tempfile.TemporaryDirectory(prefix="report rerun ") as temporary_dir:
            fixture = self._create_rerun_fixture(Path(temporary_dir))
            manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
            manifest["coverage"]["baseline_db"] = str(fixture["coverage_root"])
            fixture["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Coverage baseline must be below"):
                run_report_rerun(fixture["manifest"], self._report_environment(), _Log())

    def test_same_named_targets_export_distinct_supplements(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            rerun_script = root / "rerun.sh"
            suffixes = root / "suffixes.txt"
            rerun_script.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "printf '%s\\n' \"$SIMMER_REPORT_RERUN_DIR_SUFFIX\" >> {}\n"
                "mkdir -p \"$SIMMER_REPORT_RERUN_COVERAGE_DIR\"\n".format(shlex.quote(str(suffixes))),
                encoding="utf-8",
            )
            rerun_script.chmod(0o755)
            artifact_dir = root / "report_coverage" / "revision" / "bench"

            supplements = [
                _run_failed_test(
                    {
                        "test": "smoke",
                        "target": target,
                        "seed": 42,
                        "iteration": 1,
                        "rerun_script": str(rerun_script),
                    }, artifact_dir, "revision", project_dir, _Log()) for target in ("//pkg_a:smoke", "//pkg_b:smoke")
            ]

            self.assertNotIn(None, supplements)
            supplement_paths = [path for path in supplements if path is not None]
            self.assertEqual(2, len({path.name for path in supplement_paths}))
            self.assertTrue(
                all(path.name.startswith("smoke_") and path.name.endswith("_42_i1.vdb") for path in supplement_paths))
            self.assertEqual(2, len(set(suffixes.read_text(encoding="utf-8").splitlines())))

    def test_long_test_name_keeps_rerun_directory_component_within_name_max(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            rerun_script = root / "rerun.sh"
            rerun_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            rerun_script.chmod(0o755)
            captured_environment = {}

            def export_coverage(_command, **kwargs):
                captured_environment.update(kwargs["env"])
                Path(kwargs["env"]["SIMMER_REPORT_RERUN_COVERAGE_DIR"]).mkdir(parents=True)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            test_name = "t" * 220
            failed_test = {
                "test": test_name,
                "target": "//very/long/package/path:{}".format(test_name),
                "seed": 42,
                "iteration": 1,
                "rerun_script": str(rerun_script),
            }
            with mock.patch("lib.report_rerun.run_bounded_process", side_effect=export_coverage):
                supplement = _run_failed_test(failed_test, root / "artifacts", "20260720_120000_000001", project_dir,
                                              _Log())

            suffix = captured_environment["SIMMER_REPORT_RERUN_DIR_SUFFIX"]
            if supplement is None:
                self.fail("successful rerun did not export coverage")
            self.assertTrue(suffix.startswith("_i1_report_rerun_"))
            self.assertLessEqual(len(supplement.name.encode("utf-8")), 255)

    def test_bare_simmer_launcher_is_resolved_from_path(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            launcher = root / "bin" / "simmer"
            launcher.parent.mkdir()
            launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            launcher.chmod(0o755)
            captured_launcher = root / "captured-launcher.txt"
            rerun_script = root / "rerun.sh"
            rerun_script.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "printf '%s\\n' \"$SIMMER_BIN\" > {}\n"
                "mkdir -p \"$SIMMER_REPORT_RERUN_COVERAGE_DIR\"\n".format(shlex.quote(str(captured_launcher))),
                encoding="utf-8",
            )
            rerun_script.chmod(0o755)

            path = str(launcher.parent) + os.pathsep + os.environ["PATH"]
            original_cwd = os.getcwd()
            try:
                os.chdir(root)
                for command in ("simmer", "./bin/simmer"):
                    with self.subTest(command=command), mock.patch.object(sys, "argv", [command]), \
                         mock.patch.dict(os.environ, {"PATH": path}):
                        os.environ.pop("SIMMER_BIN", None)
                        _run_failed_test(
                            {
                                "test": "smoke",
                                "target": "//pkg:smoke",
                                "seed": 42,
                                "iteration": 1,
                                "rerun_script": str(rerun_script),
                            },
                            root / "report_coverage" / "revision" / "bench",
                            "revision",
                            project_dir,
                            _Log(),
                        )

                    self.assertTrue(Path(captured_launcher.read_text(encoding="utf-8").strip()).samefile(launcher))
            finally:
                os.chdir(original_cwd)

    def test_partial_result_updates_only_successful_iterations(self):
        trd = [
            ["bench", "vcomp", "", "1", "", "", "1", "", ""],
            ["", "test", "0:00:01", "1", "", "2", "3", "", "smoke", "//unit_a:test"],
            ["", "test", "0:00:01", "", "", "1", "1", "", "other", "//unit_b:test"],
        ]
        category_stats = {
            "smoke": {
                "total": 1,
                "executed": 1,
                "passed": 0
            },
            "other": {
                "total": 1,
                "executed": 1,
                "passed": 0
            },
        }

        updated_trd, updated_categories = _updated_results(
            trd,
            [{
                "bench": "bench",
                "target": "//unit_a:test"
            }],
            category_stats,
        )

        self.assertEqual("2", updated_trd[1][3])
        self.assertEqual("1", updated_trd[1][5])
        self.assertEqual("", updated_trd[2][3])
        self.assertEqual("1", updated_trd[2][5])
        self.assertEqual(0, updated_categories["smoke"]["passed"])
        self.assertEqual(0, updated_categories["other"]["passed"])

    def test_malformed_failed_test_is_rejected_as_a_value_error(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            manifest_path = root / "malformed.rerun.json"
            manifest_path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "webroot_dir": str(root / "web"),
                    "project_dir": str(root / "project"),
                    "regression_dir": str(root / "results"),
                    "header": {
                        "branch": "main",
                        "commit": "",
                        "coverage_enabled": True,
                        "project_name": "project",
                        "revision": "abc",
                        "simulator": "VCS",
                        "tag": "",
                        "time": "20260719_120000_000001",
                        "username": "user",
                    },
                    "trd": [["bench", "vcomp", "", "1", "", "", "1", "", ""]],
                    "category_stats": {},
                    "coverage": {
                        "baseline_db": str(root / "baseline.vdb"),
                        "urg_argv": ["urg"],
                    },
                    "failed_tests": [{}],
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "failed test requires a non-empty bench string"):
                run_report_rerun(manifest_path, self._report_environment(), _Log())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["failed_tests"] = [{
                "bench": "../bench",
                "test": "test",
                "target": "//unit:test",
                "seed": 42,
                "rerun_script": str(root / "results" / "rerun.sh"),
            }]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe bench path component"):
                run_report_rerun(manifest_path, self._report_environment(), _Log())

    def test_all_failed_reruns_leave_no_revision_artifact(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project_dir = root / "project"
            regression_dir = root / "results"
            project_dir.mkdir()
            coverage_root = regression_dir / "report_coverage"
            baseline = coverage_root / "original" / "bench" / "baseline.vdb"
            baseline.mkdir(parents=True)
            rerun_script = regression_dir / "failed" / "rerun.sh"
            rerun_script.parent.mkdir(parents=True)
            rerun_script.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            rerun_script.chmod(0o755)
            manifest_path = root / "original.rerun.json"
            manifest_path.write_text(
                json.dumps({
                    "schema_version":
                    1,
                    "webroot_dir":
                    str(root / "web"),
                    "project_dir":
                    str(project_dir),
                    "regression_dir":
                    str(regression_dir),
                    "header": {
                        "branch": "main",
                        "commit": "",
                        "coverage_enabled": True,
                        "project_name": "project",
                        "revision": "abc",
                        "simulator": "VCS",
                        "tag": "",
                        "time": "20260719_120000_000001",
                        "username": "user",
                    },
                    "trd": [
                        ["bench", "vcomp", "", "1", "", "", "1", "", ""],
                        ["", "test", "0:00:01", "", "", "1", "1", "", "", "//unit:test"],
                    ],
                    "category_stats": {},
                    "coverage": {
                        "baseline_db": str(baseline),
                        "urg_argv": ["/bin/false"],
                    },
                    "failed_tests": [{
                        "bench": "bench",
                        "test": "test",
                        "target": "//unit:test",
                        "seed": 42,
                        "iteration": 2,
                        "rerun_script": str(rerun_script),
                    }],
                }),
                encoding="utf-8",
            )

            status = run_report_rerun(manifest_path, self._report_environment(), _Log())

            self.assertEqual(1, status)
            self.assertEqual(["original"], self._coverage_revisions(coverage_root))
            self.assertTrue(baseline.is_dir())
            self.assertFalse((root / "web").exists())


if __name__ == "__main__":
    unittest.main()
