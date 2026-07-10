import unittest

from lib.regression_report import regression_history_series


class RegressionReportTest(unittest.TestCase):
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
