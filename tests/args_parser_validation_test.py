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

    def test_default_wave_end_allows_late_wave_start(self):
        options = parse_args(["--waves", "--wave-start", "100000000"])

        self.assertEqual(99999999, options.wave_end)
        self.assertFalse(options.wave_end_was_explicit)

    def test_explicit_wave_end_must_follow_wave_start(self):
        self.assert_parse_error(["--waves", "--wave-start", "20", "--wave-end", "10"])
        self.assert_parse_error(["--waves", "--wave-start", "100000000", "--wave-end", "99999999"])

    def test_uvm_max_quit_count_rejects_negative_values_but_allows_zero(self):
        self.assert_parse_error(["--uvm-max-quit-count", "-1"])
        self.assertEqual(0, parse_args(["--uvm-max-quit-count", "0"]).uvm_max_quit_count)


if __name__ == "__main__":
    unittest.main()
