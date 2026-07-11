import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lib.regression_report import RegressionReport, create_template_environment, regression_history_series


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
                    "timestamp": "</script>"
                }],
            )
        self.assertIn("&lt;bench&gt;", report_html)
        self.assertIn("%3C/script%3E.html", report_html)
        self.assertNotIn("</script>", report_html)
        self.assertIn("Regression Dashboard", report_html)
        self.assertIn("Code Coverage", report_html)
        self.assertIn("heat-good", report_html)
        self.assertNotIn("_static", report_html)
        self.assertNotIn("Chart.js", report_html)

    def test_history_keeps_code_and_functional_coverage_separate(self):
        regressions = {
            "20260710_120000": {
                "passrate": 90.0,
                "cov_code": 81.0,
                "cov_func": 72.0
            },
            "20260711_120000": {
                "passrate": 95.0,
                "cov_code": 84.0,
                "cov_func": 76.0
            },
        }

        self.assertEqual(
            ([90.0, 95.0], [81.0, 84.0], [72.0, 76.0]),
            regression_history_series(regressions, list(regressions)),
        )

    def test_report_handles_zero_tests_partial_coverage_and_untagged_header(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
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
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "empty_test", "", "", "", "", "0", "", ""),
            ]

            report.run(header, trd, {"bench": {"cc": {"Overall": "75%"}}}, {})

            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            regressions = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            summary = regressions[header["time"]]
            self.assertEqual(0.0, summary["passrate"])
            self.assertEqual(75.0, summary["cov_code"])
            self.assertIsNone(summary["cov_func"])
            self.assertTrue((bench_path / "index.html").is_file())
            report_html = (bench_path / "index.html").read_text(encoding="utf-8")
            self.assertGreaterEqual(report_html.count("N/A"), 2)

    def test_report_retention_removes_snapshot_and_timestamp_logs(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
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
                timestamp = "20260101_{:06d}".format(index)
                regressions[timestamp] = {
                    "passrate": 100,
                    "cov_code": 0,
                    "cov_func": 0,
                    "logs": [],
                }
            oldest = min(regressions)
            (bench_path / "regressions.json").write_text(json.dumps(regressions), encoding="utf-8")
            (bench_path / "{}.html".format(oldest)).write_text("old", encoding="utf-8")
            old_logs = bench_path / "logs" / oldest
            old_logs.mkdir(parents=True)
            (old_logs / "old.log").write_text("old", encoding="utf-8")

            report.run(header, trd, {}, {})

            retained = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            self.assertEqual(30, len(retained))
            self.assertNotIn(oldest, retained)
            self.assertFalse((bench_path / "{}.html".format(oldest)).exists())
            self.assertFalse(old_logs.exists())


if __name__ == "__main__":
    unittest.main()
