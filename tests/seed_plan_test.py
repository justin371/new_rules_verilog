import unittest

from lib.seed_plan import ordered_regression_tests, plan_test_seeds


class SeedPlanTest(unittest.TestCase):

    def test_seed_mapping_does_not_depend_on_discovery_order(self):
        first = {
            "//z:tb": {
                "//z/tests:second": 2,
                "//z/tests:first": 1
            },
            "//a:tb": {
                "//a/tests:smoke": 1
            },
        }
        reversed_order = {
            "//a:tb": {
                "//a/tests:smoke": 1
            },
            "//z:tb": {
                "//z/tests:first": 1,
                "//z/tests:second": 2
            },
        }

        self.assertEqual(ordered_regression_tests(first), ordered_regression_tests(reversed_order))
        self.assertEqual(plan_test_seeds(first, "0"), plan_test_seeds(reversed_order, "0"))


if __name__ == "__main__":
    unittest.main()
