import tempfile
import unittest
from pathlib import Path

from bin import check_test


class CheckTestFastPathTest(unittest.TestCase):
    def setUp(self):
        check_test.active_signatures = list(check_test.default_error_signatures)
        check_test.compile_error_regex()

    def _log(self, contents):
        path = Path(tempfile.mkdtemp()) / "stdout.log"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_static_log_fast_path_finds_finish_metadata_and_errors(self):
        path = self._log("SVSEED 123\nUVM_ERROR @ 10\n--- UVM Report Summary ---\n")

        errors, seeds, _, finished = check_test.scan_static_log(path, 25)

        self.assertEqual(["UVM_ERROR @ 10\n"], errors)
        self.assertEqual(["SVSEED 123\n"], seeds)
        self.assertTrue(finished)

    def test_dynamic_signature_log_uses_existing_fallback(self):
        path = self._log("TEST_CHECK_DISABLE: UVM_ERROR\n--- UVM Report Summary ---\n")

        self.assertIsNone(check_test.scan_static_log(path, 25))

    def test_uvm_summary_with_nonzero_error_count_fails(self):
        path = self._log("--- UVM Report Summary ---\nUVM_ERROR :    1\nUVM_FATAL :    0\n")

        errors, _, _, finished = check_test.scan_static_log(path, 25)

        self.assertEqual(["UVM_ERROR :    1\n"], errors)
        self.assertTrue(finished)

    def test_project_pass_and_fail_patterns_are_configurable(self):
        pass_regex = check_test.compile_patterns([r"^PROJECT PASS$"])
        fail_regex = check_test.compile_patterns([r"^PROJECT FAIL$"])
        path = self._log("PROJECT FAIL\nPROJECT PASS\n")

        errors, _, _, finished = check_test.scan_static_log(
            path,
            25,
            extra_error_regex=fail_regex,
            required_finish_regex=pass_regex,
        )

        self.assertEqual(["PROJECT FAIL\n"], errors)
        self.assertTrue(finished)


if __name__ == "__main__":
    unittest.main()
