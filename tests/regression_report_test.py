import os
import tempfile
import unittest
from pathlib import Path

from lib.regression_report import create_template_environment, regression_history_series


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
        logs_html = environment.get_template(
            "regression_report_templates/logs_template.html.j2",
        ).render(
            project_name="<project>",
            bench_name="bench",
            logs=['bad\"name.log'],
        )
        self.assertIn("&lt;project&gt;", logs_html)
        self.assertIn("bad%22name.log", logs_html)
        self.assertNotIn("</li>>", logs_html)

        report_html = environment.get_template(
            "regression_report_templates/regression_report_template.html.j2",
        ).render(
            bench_name="bench",
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
        )
        self.assertIn(r"\u003c/script\u003e", report_html)
        self.assertNotIn("</botton>", report_html)
        self.assertNotIn("openLocalFolderOrFile", report_html)

    def test_history_keeps_code_and_functional_coverage_separate(self):
        regressions = {
            "20260710_120000": {"passrate": 90.0, "cov_code": 81.0, "cov_func": 72.0},
            "20260711_120000": {"passrate": 95.0, "cov_code": 84.0, "cov_func": 76.0},
        }

        self.assertEqual(
            ([90.0, 95.0], [81.0, 84.0], [72.0, 76.0]),
            regression_history_series(regressions, list(regressions)),
        )


if __name__ == "__main__":
    unittest.main()
