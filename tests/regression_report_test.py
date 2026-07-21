import json
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lib.regression_report import (
    RegressionReport,
    coverage_artifact_lock,
    create_template_environment,
    regression_history_series,
)


class _Log:

    def warning(self, *_args, **_kwargs):
        pass


class RegressionReportTest(unittest.TestCase):

    def _report_environment(self):
        runfiles_root = Path(os.environ["TEST_SRCDIR"]) / os.environ.get("TEST_WORKSPACE", "__main__")
        return create_template_environment(runfiles_root / "bin/templates")

    def test_report_environment_escapes_html_only(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            template_dir = Path(temporary_dir)
            (template_dir / "report.html.j2").write_text("{{ value }}", encoding="utf-8")
            (template_dir / "script.sh.j2").write_text("{{ value }}", encoding="utf-8")
            environment = create_template_environment(template_dir)

            value = '<script>alert("unsafe")</script>'
            self.assertEqual(
                '&lt;script&gt;alert(&#34;unsafe&#34;)&lt;/script&gt;',
                environment.get_template("report.html.j2").render(value=value),
            )
            self.assertEqual(value, environment.get_template("script.sh.j2").render(value=value))

    def test_reserved_report_path_components_are_rejected(self):
        header = {
            "branch": "main",
            "commit": "",
            "project_name": "project",
            "revision": "abc",
            "simulator": "VCS",
            "tag": "",
            "time": "20260719_120000_000001",
            "username": "user",
        }
        trd = [("bench", "vcomp", "", "1", "", "", "1", "", "")]
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            with self.subTest(component="project"), self.assertRaisesRegex(ValueError, "Reserved project name"):
                report.run(dict(header, project_name="index.html"), trd, {}, {})
            with self.subTest(component="bench"), self.assertRaisesRegex(ValueError, "Reserved bench name"):
                report.run(header, [("index.html", ) + trd[0][1:]], {}, {})

    def test_report_locks_do_not_collide_with_projects_or_follow_legacy_symlinks(self):
        header = {
            "branch": "main",
            "commit": "",
            "project_name": ".project.lock",
            "revision": "abc",
            "simulator": "VCS",
            "tag": "",
            "time": "20260719_120000_000001",
            "username": "user",
        }
        trd = [("bench", "vcomp", "", "1", "", "", "1", "", "")]
        with tempfile.TemporaryDirectory() as temporary_dir:
            for project_name in (".project.lock", "project"):
                report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
                report.run(dict(header, project_name=project_name), trd, {}, {})

        with tempfile.TemporaryDirectory() as temporary_dir:
            report_root = Path(temporary_dir) / "regression_report"
            report_root.mkdir()
            outside_lock = Path(temporary_dir) / "outside.lock"
            outside_lock.write_text("keep\n", encoding="utf-8")
            (report_root / ".project.lock").symlink_to(outside_lock)
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)

            report.run(dict(header, project_name="project"), trd, {}, {})

            self.assertEqual("keep\n", outside_lock.read_text(encoding="utf-8"))

    def test_report_rejects_symlinked_project_directory(self):
        header = {
            "branch": "main",
            "commit": "",
            "project_name": "project",
            "revision": "abc",
            "simulator": "VCS",
            "tag": "",
            "time": "20260719_120000_000001",
            "username": "user",
        }
        trd = [("bench", "vcomp", "", "1", "", "", "1", "", "")]
        with tempfile.TemporaryDirectory() as temporary_dir:
            outside = Path(temporary_dir) / "outside"
            outside.mkdir()
            sentinel = outside / "sentinel"
            sentinel.write_text("keep\n", encoding="utf-8")
            report_root = Path(temporary_dir) / "web" / "regression_report"
            report_root.mkdir(parents=True)
            (report_root / "project").symlink_to(outside, target_is_directory=True)
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(),
                                      str(Path(temporary_dir) / "web"))

            with self.assertRaisesRegex(ValueError, "symlink"):
                report.run(header, trd, {}, {})

            self.assertEqual("keep\n", sentinel.read_text(encoding="utf-8"))

    def test_real_report_templates_escape_dynamic_content(self):
        environment = self._report_environment()
        logs_html = environment.get_template("regression_report_templates/logs_template.html.j2", ).render(
            project_name="<project>",
            bench_name="bench",
            logs=['bad\"name.log'],
        )
        self.assertIn("&lt;project&gt;", logs_html)
        self.assertIn("bad%22name.log", logs_html)
        self.assertNotIn("</li>>", logs_html)

        report_html = environment.get_template(
            "regression_report_templates/regression_report_template.html.j2", ).render(
                bench_name="<bench>",
                cc_info={},
                cf_info={},
                header={
                    "branch": "main",
                    "commit": "https://example.com",
                    "coverage_enabled": True,
                    "project_name": "project",
                    "revision": "abc",
                    "simulator": "VCS",
                    "tag": "",
                    "time": "20260711_120000",
                    "username": "user",
                },
                passrate_list=[100.0],
                processed_category_stats=[],
                project={"project": ["bench"]},
                regression_details=[],
                regressions=["</script>"],
                history=[{
                    "timestamp": "</script>",
                    "coverage_enabled": False,
                }, {
                    "timestamp": "covered",
                    "coverage_enabled": True,
                }],
            )
        self.assertIn("&lt;bench&gt;", report_html)
        self.assertIn("%3C/script%3E.html", report_html)
        self.assertNotIn("</script>", report_html)
        self.assertIn("Regression Dashboard", report_html)
        self.assertIn("Total Coverage", report_html)
        self.assertNotIn('<th scope="col">Total Coverage</th>', report_html)
        self.assertIn("Code Coverage", report_html)
        self.assertIn("heat-good", report_html)
        self.assertNotIn("_static", report_html)
        self.assertNotIn("Chart.js", report_html)

    def test_report_hides_coverage_when_vcs_coverage_is_disabled(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "coverage_enabled": False,
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260719_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]

            report.run(
                header,
                trd,
                {"bench": {
                    "total": "90%",
                    "cc": {
                        "Overall": "91%"
                    },
                    "cf": {
                        "Overall": "89%"
                    },
                }},
                {},
            )

            report_root = Path(temporary_dir) / "regression_report"
            bench_path = report_root / "project" / "bench"
            summary = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))[header["time"]]
            self.assertFalse(summary["coverage_enabled"])
            self.assertIsNone(summary["cov_total"])
            self.assertNotIn("Total Coverage", (bench_path / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("Total Coverage", (report_root / "project" / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("Total Coverage", (report_root / "index.html").read_text(encoding="utf-8"))

    def test_existing_revision_timestamp_is_immutable(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260719_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            report.run(header, trd, {}, {})
            report_root = Path(temporary_dir) / "regression_report"
            files_before = {
                path.relative_to(report_root): path.read_bytes()
                for path in report_root.rglob("*") if path.is_file() and ".locks" not in path.parts
            }

            with self.assertRaisesRegex(FileExistsError, "Report revision already exists"):
                report.run(header, trd, {"bench": {"total": "99%"}}, {})

            files_after = {
                path.relative_to(report_root): path.read_bytes()
                for path in report_root.rglob("*") if path.is_file() and ".locks" not in path.parts
            }
            self.assertEqual(files_before, files_after)

    def test_termination_signal_rolls_back_partial_publication(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260719_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]

            def terminate_during_publication():
                signal_handler = signal.getsignal(signal.SIGTERM)
                if not callable(signal_handler):
                    self.fail("SIGTERM publication handler was not installed")
                signal_handler(signal.SIGTERM, None)

            with mock.patch.object(report, "render_home_page", side_effect=terminate_during_publication), \
                 self.assertRaisesRegex(KeyboardInterrupt, "interrupted by signal"):
                report.run(header, trd, {}, {})

            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            self.assertFalse((bench_path / "regressions.json").exists())
            self.assertFalse((bench_path / "{}.html".format(header["time"])).exists())

            terminated_header = dict(header, time="20260719_120001_000001")
            with mock.patch.object(report, "render_home_page", side_effect=SystemExit("terminated")), \
                 self.assertRaisesRegex(SystemExit, "terminated"):
                report.run(terminated_header, trd, {}, {})

            self.assertFalse((bench_path / "regressions.json").exists())
            self.assertFalse((bench_path / "{}.html".format(terminated_header["time"])).exists())

    def test_mixed_project_hides_aggregate_coverage_columns(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            environment = self._report_environment()
            base_header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "tag": "",
                "username": "user",
            }
            vcs_header = dict(
                base_header,
                coverage_enabled=True,
                simulator="VCS",
                time="20260719_120000_000001",
            )
            xrun_header = dict(
                base_header,
                coverage_enabled=False,
                simulator="XRUN",
                time="20260719_120001_000001",
            )
            vcs_trd = [
                ("vcs_bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            xrun_trd = [
                ("xrun_bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]

            RegressionReport(SimpleNamespace(log=_Log()), environment, temporary_dir).run(
                vcs_header,
                vcs_trd,
                {"vcs_bench": {
                    "total": "90%"
                }},
                {},
            )
            RegressionReport(SimpleNamespace(log=_Log()), environment, temporary_dir).run(
                xrun_header,
                xrun_trd,
                {},
                {},
            )

            report_root = Path(temporary_dir) / "regression_report"
            self.assertNotIn("Total Coverage", (report_root / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("Total Coverage", (report_root / "project" / "index.html").read_text(encoding="utf-8"))
            self.assertIn("Total Coverage",
                          (report_root / "project" / "vcs_bench" / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("Total Coverage",
                             (report_root / "project" / "xrun_bench" / "index.html").read_text(encoding="utf-8"))

    def test_report_writes_failed_rerun_manifest(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), root / "web")
            baseline = root / "results" / "report_coverage" / "original" / "bench" / "baseline.vdb"
            baseline.mkdir(parents=True)
            rerun_script = root / "results" / "failed" / "rerun.sh"
            rerun_script.parent.mkdir(parents=True)
            rerun_script.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            header = {
                "branch": "main",
                "commit": "",
                "coverage_enabled": True,
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260719_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "", "", "1", "1", "", "", "//unit:test"),
            ]
            rerun_context = {
                "bench": {
                    "project_dir":
                    str(root / "project"),
                    "regression_dir":
                    str(root / "results"),
                    "coverage": {
                        "artifact_dir": str(baseline.parent),
                        "baseline_db": str(baseline),
                        "urg_argv": ["runmod", "vcs", "--", "urg"],
                        "urg_parallel": False,
                        "urg_show_tests": False,
                    },
                    "failed_tests": [{
                        "bench": "bench",
                        "test": "test",
                        "target": "//unit:test",
                        "seed": 42,
                        "rerun_script": str(rerun_script),
                    }],
                },
            }

            report.run(header, trd, {"bench": {"total": "80%"}}, {}, rerun_context=rerun_context)

            bench_path = root / "web" / "regression_report" / "project" / "bench"
            manifest_path = bench_path / "20260719_120000_000001.rerun.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(1, manifest["schema_version"])
            self.assertEqual("VCS", manifest["header"]["simulator"])
            self.assertEqual(str(baseline), manifest["coverage"]["baseline_db"])
            self.assertEqual("//unit:test", manifest["failed_tests"][0]["target"])
            self.assertIn("simmer --rerun-report", (bench_path / "index.html").read_text(encoding="utf-8"))

    def test_history_keeps_code_and_functional_coverage_separate(self):
        regressions = {
            "20260710_120000": {
                "passrate": 90.0,
                "cov_total": 78.0,
                "cov_code": 81.0,
                "cov_func": 72.0
            },
            "20260711_120000": {
                "passrate": 95.0,
                "cov_total": 82.0,
                "cov_code": 84.0,
                "cov_func": 76.0
            },
        }

        self.assertEqual(
            ([90.0, 95.0], [78.0, 82.0], [81.0, 84.0], [72.0, 76.0]),
            regression_history_series(regressions, list(regressions)),
        )

    def test_report_handles_zero_tests_partial_coverage_and_untagged_header(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "coverage_enabled": True,
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260711_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "empty_test", "", "", "", "", "0", "", ""),
            ]

            report.run(
                header,
                trd,
                {"bench": {
                    "total": "80%",
                    "vendor_score": "82%",
                    "cc": {
                        "Overall": "75%"
                    },
                }},
                {},
            )

            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            regressions = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            summary = regressions[header["time"]]
            self.assertEqual(0.0, summary["passrate"])
            self.assertEqual(80.0, summary["cov_total"])
            self.assertEqual(75.0, summary["cov_code"])
            self.assertIsNone(summary["cov_func"])
            self.assertEqual(82.0, summary["cov_vendor_score"])
            self.assertTrue((bench_path / "index.html").is_file())
            report_html = (bench_path / "index.html").read_text(encoding="utf-8")
            self.assertGreaterEqual(report_html.count("N/A"), 2)

    def test_compile_failure_log_is_copied_and_linked(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            compile_dir = Path(temporary_dir) / "compile"
            compile_dir.mkdir()
            compile_log = compile_dir / "cmp.log"
            compile_log.write_text("compile failed\n", encoding="utf-8")
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260711_120000_000001",
                "username": "user",
            }

            report.run(
                header,
                [("bench", "vcomp", "0:00:01", "", "", "1", "1", str(compile_log), "")],
                {},
                {},
            )

            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            copied_log = bench_path / "logs" / header["time"] / "vcomp_01_compile.log"
            self.assertEqual("compile failed\n", copied_log.read_text(encoding="utf-8"))
            report_html = (bench_path / "index.html").read_text(encoding="utf-8")
            self.assertIn("{}/001_vcomp.html".format(header["time"]), report_html)
            logs_html = (copied_log.parent / "001_vcomp.html").read_text(encoding="utf-8")
            self.assertIn("vcomp_01_compile.log", logs_html)

    def test_report_retention_removes_snapshot_and_timestamp_logs(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                temporary_dir,
            )
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "XRUN",
                "tag": "",
                "time": "20260711_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            bench_path.mkdir(parents=True)
            regressions = {}
            for index in range(30):
                timestamp = "20270101_{:06d}".format(index)
                regressions[timestamp] = {
                    "passrate": 100,
                    "cov_code": 0,
                    "cov_func": 0,
                    "logs": [],
                }
            unsafe_timestamp = "../outside"
            regressions[unsafe_timestamp] = {
                "passrate": 0,
                "cov_code": 0,
                "cov_func": 0,
                "logs": [],
            }
            oldest = min(timestamp for timestamp in regressions if timestamp != unsafe_timestamp)
            old_coverage = regression_dir / "report_coverage" / oldest / "bench"
            old_coverage.mkdir(parents=True)
            old_manifest = bench_path / "{}.rerun.json".format(oldest)
            old_manifest.write_text("{}\n", encoding="utf-8")
            regressions[oldest]["rerun_manifest"] = old_manifest.name
            regressions[oldest]["coverage_artifact_dir"] = str(old_coverage)
            regressions[oldest]["logs"] = [["regressions.json"]]
            (bench_path / "regressions.json").write_text(json.dumps(regressions), encoding="utf-8")
            (bench_path / "{}.html".format(oldest)).write_text("old", encoding="utf-8")
            old_logs = bench_path / "logs" / oldest
            old_logs.mkdir(parents=True)
            (old_logs / "old.log").write_text("old", encoding="utf-8")
            outside_page = bench_path.parent / "outside.html"
            outside_page.write_text("outside", encoding="utf-8")

            with mock.patch("lib.regression_report._write_json_atomic", side_effect=OSError("history write failed")):
                with self.assertRaisesRegex(OSError, "history write failed"):
                    report.run(header, trd, {}, {})

            unchanged = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            self.assertIn(oldest, unchanged)
            self.assertTrue((bench_path / "{}.html".format(oldest)).is_file())
            self.assertTrue(old_logs.is_dir())
            self.assertTrue(old_manifest.is_file())
            self.assertTrue(old_coverage.is_dir())
            self.assertTrue(outside_page.is_file())

            report.run(header, trd, {}, {})

            retained = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            self.assertEqual(30, len(retained))
            self.assertNotIn(oldest, retained)
            self.assertNotIn(unsafe_timestamp, retained)
            self.assertIn(header["time"], retained)
            self.assertTrue((bench_path / "{}.html".format(header["time"])).is_file())
            self.assertIn(header["time"], (bench_path.parent / "index.html").read_text(encoding="utf-8"))
            self.assertIn(header["time"], (bench_path.parent.parent / "index.html").read_text(encoding="utf-8"))
            self.assertFalse((bench_path / "{}.html".format(oldest)).exists())
            self.assertFalse(old_logs.exists())
            self.assertFalse(old_manifest.exists())
            self.assertFalse(old_coverage.exists())
            self.assertTrue(outside_page.is_file())

    def test_active_coverage_baseline_is_not_removed_by_retention(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            timestamp = "20260719_120000_000001"
            artifact_dir = regression_dir / "report_coverage" / timestamp / "bench"
            artifact_dir.mkdir(parents=True)
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                temporary_dir,
            )

            with coverage_artifact_lock(regression_dir, timestamp, shared=True):
                report._remove_history_artifacts(
                    Path(temporary_dir) / "regression_report" / "project" / "bench",
                    timestamp,
                    {"coverage_artifact_dir": str(artifact_dir)},
                )
                self.assertTrue(artifact_dir.is_dir())

            report._remove_history_artifacts(
                Path(temporary_dir) / "regression_report" / "project" / "bench",
                timestamp,
                {"coverage_artifact_dir": str(artifact_dir)},
            )
            self.assertFalse(artifact_dir.exists())

    def test_deferred_coverage_cleanup_is_retried_after_reader_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            bench_path.mkdir(parents=True)
            regressions = {}
            for index in range(30):
                timestamp = "20270101_{:06d}".format(index)
                regressions[timestamp] = {
                    "passrate": 100,
                    "logs": [],
                }
            oldest = min(regressions)
            old_coverage = regression_dir / "report_coverage" / oldest / "bench"
            old_coverage.mkdir(parents=True)
            regressions[oldest]["coverage_artifact_dir"] = str(old_coverage)
            (bench_path / "regressions.json").write_text(json.dumps(regressions), encoding="utf-8")
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260719_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            rcfg = SimpleNamespace(log=_Log(), regression_dir=str(regression_dir))

            with coverage_artifact_lock(regression_dir, oldest, shared=True):
                RegressionReport(rcfg, self._report_environment(), temporary_dir).run(header, trd, {}, {})
                self.assertTrue(old_coverage.is_dir())

            cleanup_path = regression_dir / "report_coverage" / ".locks" / "coverage_cleanup.json"
            self.assertTrue(cleanup_path.is_file())
            RegressionReport(rcfg, self._report_environment(),
                             temporary_dir).run(dict(header, time="20260720_120000_000001"), trd, {}, {})

            self.assertFalse(old_coverage.exists())
            self.assertFalse(cleanup_path.exists())

    def test_deferred_cleanup_queue_uses_regression_scoped_lock(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                Path(temporary_dir) / "web",
            )

            def load_queue_while_locked(_path, default):
                with coverage_artifact_lock(regression_dir, "deferred_coverage_cleanup", shared=False,
                                            blocking=False) as acquired:
                    self.assertFalse(acquired)
                return default

            with mock.patch("lib.regression_report._load_json", side_effect=load_queue_while_locked):
                report._cleanup_committed_history()

    def test_interrupted_history_cleanup_persists_coverage_retry_and_propagates(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            timestamp = "20260719_120000_000001"
            artifact_dir = regression_dir / "report_coverage" / timestamp / "bench"
            artifact_dir.mkdir(parents=True)
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                temporary_dir,
            )
            report._pending_history_cleanup = [
                (Path(temporary_dir) / "bench", timestamp, {
                    "coverage_artifact_dir": str(artifact_dir),
                }),
            ]

            with mock.patch.object(report, "_remove_history_artifacts",
                                   side_effect=KeyboardInterrupt("cleanup interrupted")), \
                 self.assertRaisesRegex(KeyboardInterrupt, "cleanup interrupted"):
                report._cleanup_committed_history()

            cleanup_path = regression_dir / "report_coverage" / ".locks" / "coverage_cleanup.json"
            records = json.loads(cleanup_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact_dir.resolve(), Path(records[0]["artifact_dir"]))
            self.assertTrue(artifact_dir.is_dir())

            RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                temporary_dir,
            )._cleanup_committed_history()
            self.assertFalse(artifact_dir.exists())
            self.assertFalse(cleanup_path.exists())

    def test_deferred_coverage_cleanup_rejects_foreign_regression_root(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            active_regression_dir = Path(temporary_dir) / "active"
            foreign_regression_dir = Path(temporary_dir) / "foreign"
            timestamp = "20260719_120000_000001"
            foreign_artifact = foreign_regression_dir / "report_coverage" / timestamp / "bench"
            foreign_artifact.mkdir(parents=True)
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(active_regression_dir)),
                self._report_environment(),
                temporary_dir,
            )

            pending = report._coverage_cleanup_pending({
                "regression_dir": str(foreign_regression_dir),
                "timestamp": timestamp,
                "artifact_dir": str(foreign_artifact),
            })

            self.assertFalse(pending)
            self.assertTrue(foreign_artifact.is_dir())

    def test_deferred_coverage_cleanup_retries_deletion_failure(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            timestamp = "20260719_120000_000001"
            artifact_dir = regression_dir / "report_coverage" / timestamp / "bench"
            artifact_dir.mkdir(parents=True)
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                temporary_dir,
            )
            record = {
                "regression_dir": str(regression_dir),
                "timestamp": timestamp,
                "artifact_dir": str(artifact_dir),
            }

            with mock.patch("lib.regression_report.shutil.rmtree", side_effect=OSError("busy")):
                self.assertTrue(report._coverage_cleanup_pending(record))

            self.assertTrue(artifact_dir.is_dir())

    def test_deferred_coverage_cleanup_rejects_timestamp_root(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            regression_dir = Path(temporary_dir) / "results"
            timestamp = "20260719_120000_000001"
            timestamp_root = regression_dir / "report_coverage" / timestamp
            artifact = timestamp_root / "bench"
            artifact.mkdir(parents=True)
            report = RegressionReport(
                SimpleNamespace(log=_Log(), regression_dir=str(regression_dir)),
                self._report_environment(),
                temporary_dir,
            )

            pending = report._coverage_cleanup_pending({
                "regression_dir": str(regression_dir),
                "timestamp": timestamp,
                "artifact_dir": str(timestamp_root),
            })

            self.assertFalse(pending)
            self.assertTrue(artifact.is_dir())

    def test_run_launcher_opens_only_this_regression_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="report launcher ") as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project name",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260716_140000_000001",
                "username": "user",
            }
            trd = [
                ("bench one", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
                ("bench two", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            report.run(header, trd, {}, {})

            launcher = report.write_run_launcher()
            if launcher is None:
                self.fail("Expected a report launcher")
            launcher_path = Path(launcher)
            self.assertEqual(
                Path(temporary_dir) / "regression_report" / "open_20260716_140000_000001.sh",
                launcher_path,
            )
            capture_path = Path(temporary_dir) / "opened reports.txt"
            browser_path = Path(temporary_dir) / "browser stub.sh"
            browser_path.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$1\" >> \"$REPORT_CAPTURE\"\n",
                encoding="utf-8",
            )
            browser_path.chmod(0o755)
            environment = dict(os.environ, BROWSER=str(browser_path), REPORT_CAPTURE=str(capture_path))

            subprocess.run([str(launcher_path)], env=environment, check=True, capture_output=True, text=True)

            self.assertTrue(os.access(launcher_path, os.X_OK))
            opened_reports = capture_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(opened_reports))
            self.assertTrue(all(path.endswith("/20260716_140000_000001.html") for path in opened_reports))
            self.assertTrue(all("index.html" not in path for path in opened_reports))


if __name__ == "__main__":
    unittest.main()
