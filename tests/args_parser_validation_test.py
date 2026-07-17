import contextlib
import io
import unittest

from bin.args_parser import parse_args


class ArgsParserValidationTest(unittest.TestCase):

    def assert_parse_error(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                parse_args(argv)
        self.assertEqual(2, raised.exception.code)

    def test_tag_filter_requires_preceding_test_selector(self):
        self.assert_parse_error(["--tag", "smoke"])
        self.assert_parse_error(["--ntag", "slow"])

    def test_wave_end_must_follow_wave_start_even_at_default_sentinel(self):
        self.assert_parse_error(["--waves", "--wave-start", "99999999"])

    def test_uvm_max_quit_count_rejects_negative_values_but_allows_zero(self):
        self.assert_parse_error(["--uvm-max-quit-count", "-1"])
        self.assertEqual(0, parse_args(["--uvm-max-quit-count", "0"]).uvm_max_quit_count)


if __name__ == "__main__":
    unittest.main()
