import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from args_parser import parse_args
from lib.simulators.vcs import VcsSimulator
from lib.simulators.xcelium import XceliumSimulator


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

    def test_category_config_is_explicitly_enabled(self):
        self.assertIsNone(parse_args([]).category_cfg)
        self.assertEqual("", parse_args(["--category-cfg"]).category_cfg)
        self.assertEqual("custom.json", parse_args(["--category-cfg", "custom.json"]).category_cfg)

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

    def test_vcs_no_compile_requires_simv(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        job_dir = Path(tempfile.mkdtemp())
        vcomp = SimpleNamespace(job_dir=str(job_dir))

        with self.assertRaises(FileNotFoundError):
            simulator.validate_reusable_compile_artifacts(vcomp)
        (job_dir / "simv").touch()
        simulator.validate_reusable_compile_artifacts(vcomp)

    def test_xcelium_batch_vwdb_and_xprop_contract(self):
        options = parse_args(["-t", "unit:test", "--simulator", "XRUN", "--waves"])
        self.assertEqual("vwdb", options.wave_type)
        self.assertFalse(options.gui)

        simulator = XceliumSimulator(options, DummyRegressionConfig(), None)
        test_job = SimpleNamespace(job_dir=tempfile.mkdtemp())
        capture = simulator.get_wave_capture_options(test_job, "/tmp/waves.tcl")
        self.assertEqual("hdl_top", capture["default_capture"])
        self.assertIn("-debug_opts verisium_pp", capture["sim_opts"])

        vcomp = DummyVcompJob()
        Path(vcomp.bench_dir, "fox_xprop.txt").touch()
        self.assertIn("fox_xprop.txt", simulator.generate_compile_options(vcomp)["xprop_cmd"])

    def test_vcs_warning_parser_accepts_message_ids(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        pattern = VcsSimulator(options, DummyRegressionConfig(), None).get_log_parsing_info()["warning_regex"]

        self.assertRegex("Warning-[INC-LDNE] Library directory does not exist", pattern)

    def test_vcs_report_runs_generated_coverage_merge_script(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--cm", "line"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        vcomp = SimpleNamespace(coverage_merge_script="/tmp/unit_vcs_cov_merge.sh")

        with mock.patch("lib.simulators.vcs.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            simulator.run_report_coverage_merge({"//unit:tb": vcomp})

        run.assert_called_once_with(
            ["bash", "/tmp/unit_vcs_cov_merge.sh"],
            capture_output=True,
            text=True,
        )

    def test_rerun_preserves_original_options_without_forcing_waves(self):
        template = self._read_repo_file("bin/templates/rerun_template.sh.j2")

        self.assertIn("{{ reproduce_args }}", template)
        self.assertNotIn("--waves --simulator", template)

    def test_simmer_log_and_profile_performance_contracts(self):
        source = self._read_repo_file("bin/simmer.py")

        self.assertIn("for warning_line in logp", source)
        self.assertNotIn("text = logp.read()", source)
        self.assertNotIn('subprocess.run(["chmod", "-R"', source)
        self.assertIn("completed without simulation log", source)
        self.assertLess(source.index('"coverage_merge"'), source.index("print_simmer_profile(rcfg, jm)"))

    def test_vcs_unit_test_rules_are_blocked_in_favor_of_two_step_flow(self):
        dv_bzl = self._read_repo_file("verilog/private/dv.bzl")
        rtl_bzl = self._read_repo_file("verilog/private/rtl.bzl")

        self.assertIn("verilog_dv_unit_test {} does not support simulator = 'VCS'", dv_bzl)
        self.assertIn("Use the VCS two-step flow via verilog_dv_tb + simmer instead.", dv_bzl)
        self.assertIn("verilog_rtl_unit_test {} does not support simulator = 'VCS'", rtl_bzl)
        self.assertIn("Use the VCS two-step flow via simmer instead.", rtl_bzl)


if __name__ == "__main__":
    unittest.main()
