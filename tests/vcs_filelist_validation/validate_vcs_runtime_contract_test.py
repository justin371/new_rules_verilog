import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from args_parser import parse_args
from lib.simulators.vcs import VcsSimulator


class DummyRegressionConfig:
    def __init__(self):
        self.regression_dir = tempfile.mkdtemp(prefix="vcs_runtime_contract_")
        self.proj_dir = os.getcwd()
        self.deferred_messages = []


class DummyVcompJob:
    def __init__(self):
        self.bench_dir = tempfile.mkdtemp(prefix="vcs_bench_")
        self.name = "unit_vcomp"


class VcsRuntimeContractTest(unittest.TestCase):
    def _read_repo_file(self, relative_path):
        test_workspace = os.environ.get("TEST_WORKSPACE", "__main__")
        manifest_file = os.environ.get("RUNFILES_MANIFEST_FILE")
        manifest_key = "{}/{}".format(test_workspace, relative_path.replace("\\", "/"))
        if manifest_file:
            for line in Path(manifest_file).read_text(encoding = "utf-8").splitlines():
                if line.startswith(manifest_key + " "):
                    return Path(line.split(" ", 1)[1]).read_text(encoding = "utf-8")

        test_srcdir = os.environ["TEST_SRCDIR"]
        return (Path(test_srcdir) / test_workspace / relative_path).read_text(encoding = "utf-8")

    def setUp(self):
        self._original_vcs_runner = os.environ.pop("RV_VCS_RUNNER", None)

    def tearDown(self):
        if self._original_vcs_runner is not None:
            os.environ["RV_VCS_RUNNER"] = self._original_vcs_runner
        else:
            os.environ.pop("RV_VCS_RUNNER", None)

    def test_normal_vcs_simmer_invocation_does_not_require_runner_override(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--waves"])

        self.assertEqual("VCS", options.simulator)
        self.assertIsNone(options.vcs_runner)
        self.assertEqual("fsdb", options.wave_type)

        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        self.assertEqual("runmod vcs --", simulator.get_tool_runner())

    def test_vcs_default_batch_disables_xprop_in_template_only(self):
        vcs_options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        xcelium_options = parse_args(["-t", "unit:test", "--simulator", "XRUN"])

        self.assertEqual("F", vcs_options.xprop)
        self.assertFalse(vcs_options.xprop_was_explicit)
        self.assertEqual("F", xcelium_options.xprop)

        simulator = VcsSimulator(vcs_options, DummyRegressionConfig(), None)
        self.assertIsNone(simulator.generate_compile_options(DummyVcompJob())["xprop_cmd"])

    def test_explicit_vcs_xprop_f_enables_compile_option(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--xprop", "F"])

        simulator = VcsSimulator(options, DummyRegressionConfig(), None)

        self.assertEqual("-xprop=xmerge", simulator.generate_compile_options(DummyVcompJob())["xprop_cmd"])

    def test_explicit_xprop_disable_still_maps_to_none(self):
        vcs_options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--xprop", "D"])

        self.assertIsNone(vcs_options.xprop)
        self.assertTrue(vcs_options.xprop_was_explicit)

    def test_jobs_option_requires_a_positive_integer(self):
        self.assertEqual(3, parse_args(["--jobs", "3"]).jobs)
        with self.assertRaises(SystemExit):
            parse_args(["--jobs", "0"])

    def test_vcs_simv_runtime_keeps_dash_f_filelist(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)

        command = simulator.get_sim_command(
            test_job=None,
            sim_opts="-f bazel_runfiles_main/unit/test_runtime_args.f +UVM_TESTNAME=test",
            vcomp_job_dir="/tmp/example_vcomp",
            log_path="/tmp/example_test/stdout.log",
        )

        self.assertIn("runmod vcs -- /tmp/example_vcomp/simv", command)
        self.assertIn("-f bazel_runfiles_main/unit/test_runtime_args.f", command)
        self.assertNotIn("-file bazel_runfiles_main/unit/test_runtime_args.f", command)
        self.assertNotIn(" -sml ", command)

    def test_vcs_smartlog_is_debug_only_by_default(self):
        default_options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        smartlog_options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--smartlog"])
        waves_options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--waves"])

        self.assertFalse(VcsSimulator(default_options, DummyRegressionConfig(), None).use_smartlog())
        self.assertTrue(VcsSimulator(smartlog_options, DummyRegressionConfig(), None).use_smartlog())
        self.assertTrue(VcsSimulator(waves_options, DummyRegressionConfig(), None).use_smartlog())

    def test_smartlog_is_vcs_only_and_simmer_profile_is_common(self):
        self.assertTrue(parse_args(["-t", "unit:test", "--simulator", "XRUN", "--simmer-profile"]).simmer_profile)
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "XRUN", "--smartlog"])

    def test_vcs_compile_template_defaults_to_incremental_compile(self):
        template = self._read_repo_file("bin/templates/vcs_compile_template.sh.j2")

        self.assertIn("mkdir -p {{ VCOMP_DIR }}/csrc", template)
        self.assertIn("-Mdir={{ VCOMP_DIR }}/csrc", template)
        self.assertIn("-Mlib={{ VCOMP_DIR }}/csrc", template)
        self.assertIn("-Mupdate", self._read_repo_file("vendors/synopsys/verilog_dv_tb_compile_args.f.template"))

    def test_vcs_unit_test_rules_are_blocked_in_favor_of_two_step_flow(self):
        dv_bzl = self._read_repo_file("verilog/private/dv.bzl")
        rtl_bzl = self._read_repo_file("verilog/private/rtl.bzl")

        self.assertIn("verilog_dv_unit_test {} does not support simulator = 'VCS'", dv_bzl)
        self.assertIn("Use the VCS two-step flow via verilog_dv_tb + simmer instead.", dv_bzl)
        self.assertIn("verilog_rtl_unit_test {} does not support simulator = 'VCS'", rtl_bzl)
        self.assertIn("Use the VCS two-step flow via simmer instead.", rtl_bzl)


if __name__ == "__main__":
    unittest.main()
