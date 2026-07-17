import os
from pathlib import Path
import unittest


class ExternalSetupSmokeTest(unittest.TestCase):

    def test_generated_verilog_filelist_contains_fixture_source(self):
        runfiles_root = Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"]
        generated_filelist = runfiles_root / "rules_verilog_setup_library.f"
        generated_entries = [line for line in generated_filelist.read_text(encoding="utf-8").splitlines() if line]

        self.assertIn("rules_verilog_external_setup_top.sv", generated_entries)
        self.assertIn("gumi_rules_verilog_setup_library.vh", generated_entries)


if __name__ == "__main__":
    unittest.main()
