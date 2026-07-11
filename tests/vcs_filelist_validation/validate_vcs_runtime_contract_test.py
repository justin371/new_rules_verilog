import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import jinja2

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from args_parser import parse_args
from lib.runtime_options import format_sim_opts_dict
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
            for line in Path(manifest_file).read_text(encoding="utf-8").splitlines():
                if line.startswith(manifest_key + " "):
                    return Path(line.split(" ", 1)[1]).read_text(encoding="utf-8")

        test_srcdir = os.environ["TEST_SRCDIR"]
        return (Path(test_srcdir) / test_workspace / relative_path).read_text(encoding="utf-8")

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

    def test_runtime_options_are_shell_escaped_once(self):
        value = "label with spaces;$(touch should_not_run)"
        formatted = format_sim_opts_dict({"+LABEL=": value})

        self.assertEqual(["+LABEL=" + value], shlex.split(formatted))

        options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        command = simulator.get_sim_command(
            test_job=None,
            sim_opts=formatted,
            vcomp_job_dir="/tmp/vcomp with spaces",
            log_path="/tmp/log with spaces/stdout.log",
        )
        self.assertIn("/tmp/vcomp with spaces/simv", shlex.split(command))
        self.assertIn("+LABEL=" + value, shlex.split(command))

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

    def test_tool_specific_arguments_are_rejected_by_the_other_backend(self):
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "VCS", "--probe-packed", "64"])
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "XRUN", "--gui"])
        with mock.patch("args_parse.parser.SIM_PLATFORM", "VCS"):
            with self.assertRaises(SystemExit):
                parse_args(["-t", "unit:test", "--probe-packed", "64"])

        common = self._read_repo_file("bin/args_parse/common.py")
        vcs = self._read_repo_file("bin/args_parse/vcs.py")
        xcelium = self._read_repo_file("bin/args_parse/xcelium.py")
        self.assertNotIn("--gui", common)
        self.assertNotIn("--wave-delta", common)
        self.assertNotIn("--probe-packed", common)
        self.assertIn("--gui", vcs)
        self.assertIn("--wave-delta", xcelium)
        self.assertIn("--probe-packed", xcelium)
        self.assertNotIn("--wave-exclude", xcelium)

    def test_wave_time_range_is_validated(self):
        with self.assertRaises(SystemExit):
            parse_args(["--wave-start", "-1"])
        with self.assertRaises(SystemExit):
            parse_args(["--wave-start", "20", "--wave-end", "10"])

    def test_xcelium_wave_template_honors_delta_and_end_time(self):
        template = self._read_repo_file("bin/templates/xrun_wave_cmd_template.tcl.j2")

        self.assertIn("-default{{ delta }}", template)
        self.assertNotIn("options.delta", template)
        self.assertIn("options.wave_end - options.wave_start", template)
        self.assertIn("database -close shm_db", template)
        self.assertIn("database -close vcd_db", template)

        rendered = jinja2.Template(template, undefined=jinja2.StrictUndefined).render(
            delta=" -event",
            options=SimpleNamespace(
                probe_packed=128,
                probe_unpacked=128,
                probes=["hdl_top.dut"],
                wave_depth=8,
                wave_end=100,
                wave_start=20,
                wave_type="shm",
            ),
            waves_db="waves.shm",
        )
        self.assertIn("-default -event", rendered)
        self.assertIn("run 80ns", rendered)
        self.assertIn("database -close shm_db", rendered)

    def test_shell_templates_preserve_failures_and_argv(self):
        coverage = self._read_repo_file("bin/templates/vcs_cov_merge_template.sh.j2")
        sim = self._read_repo_file("bin/templates/sim_template.sh.j2")
        svunit = self._read_repo_file("vendors/cadence/verilog_rtl_unit_test_svunit.sh.template")
        cdc = self._read_repo_file("vendors/cadence/verilog_rtl_cdc_test.sh.template")
        lint_templates = [
            self._read_repo_file("vendors/cadence/verilog_rtl_lint_test.sh.template"),
            self._read_repo_file("vendors/synopsys/verilog_rtl_lint_test.sh.template"),
            self._read_repo_file("vendors/real_intent/verilog_rtl_lint_test.sh.template"),
        ]

        self.assertIn("set -Eeuo pipefail", coverage)
        self.assertNotIn("final_result + sim_exit_code", sim)
        self.assertNotIn("sockets_exit_code + socket_exit_code", sim)
        self.assertNotIn('time eval "{{ simulation_command }}"', sim)
        self.assertIn("time {{ simulation_command }}", sim)
        self.assertIn('kill "${{ socket_name|upper }}_PID"', sim)
        self.assertIn("{POST_FLIST_ARGS} \\", svunit)
        self.assertIn('"${remaining_args[@]}"', svunit)
        self.assertIn("completed without cdc_run/jg.log", cdc)
        for template in lint_templates:
            self.assertIn("set -Eeuo pipefail", template)
            self.assertIn('"$@"', template)

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

    def test_vcs_coverage_uses_one_vdb_path_for_simulation_and_merge(self):
        options = parse_args([
            "-t",
            "unit:test",
            "--simulator",
            "VCS",
            "--cm",
            "line",
            "--vcs-runner",
            "site-vcs --",
        ])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        vcomp = DummyVcompJob()

        with mock.patch.object(simulator, "setup_coverage_merge"):
            compile_options = simulator.generate_compile_options(vcomp)

        self.assertTrue(vcomp.cov_work_dir.endswith(".vdb"))
        self.assertIn("-cm_dir {}".format(vcomp.cov_work_dir), compile_options["cov_opts"])

        template = self._read_repo_file("bin/templates/vcs_cov_merge_template.sh.j2")
        self.assertIn("{{ urg_command }}", template)
        self.assertIn("{{ verdi_command }}", template)

    def test_rerun_preserves_original_options_without_forcing_waves(self):
        template = self._read_repo_file("bin/templates/rerun_template.sh.j2")

        self.assertIn("{{ reproduce_args }}", template)
        self.assertIn("{{ rerun_target }}", template)
        self.assertIn("${SIMMER_BIN:-simmer}", template)
        self.assertIn("{{ project_dir }}", template)
        self.assertIn('cd "$PROJECT_DIR"', template)
        self.assertNotIn("job.vcomper.name", template)
        self.assertNotIn("--waves --simulator", template)

    def test_rerun_argument_filtering_is_positional(self):
        options = parse_args([
            "--timeout",
            "42",
            "-t",
            "unit:test",
            "--seed",
            "42",
            "--simulator",
            "VCS",
        ])

        self.assertEqual(["--timeout", "42", "--simulator", "VCS"], options.reproduce_args)

    def test_generated_helper_scripts_are_workspace_and_launcher_portable(self):
        sim_template = self._read_repo_file("bin/templates/sim_template.sh.j2")
        waves_template = self._read_repo_file("bin/templates/run_waves_template.sh.j2")

        self.assertIn("{{ check_test_path }}", sim_template)
        self.assertNotIn("bazel-bin/external/rules_verilog", sim_template)
        self.assertIn("SIMMER_WAVE_LAUNCHER", waves_template)
        self.assertNotIn("/global/tools/lsf", waves_template)

    def test_simmer_log_and_profile_performance_contracts(self):
        source = self._read_repo_file("bin/simmer.py")

        self.assertIn("for warning_line in logp", source)
        self.assertNotIn("text = logp.read()", source)
        self.assertNotIn('subprocess.run(["chmod", "-R"', source)
        self.assertIn("completed without simulation log", source)
        self.assertIn("ENV_CAPTURE_KEYS", source)
        self.assertNotIn("sorted(os.environ.items())", source)
        self.assertIn("j.jobstatus == JobStatus.FAILED", source)
        self.assertLess(source.index('"coverage_merge"'), source.index("print_simmer_profile(rcfg, jm)"))

    def test_vcs_unit_test_rules_use_simulator_specific_defaults(self):
        dv_bzl = self._read_repo_file("verilog/private/dv.bzl")
        rtl_bzl = self._read_repo_file("verilog/private/rtl.bzl")

        self.assertIn('filelist_flag = "-file"', dv_bzl)
        self.assertIn("_ut_sim_template_vcs_default", dv_bzl)
        self.assertIn('filelist_flag = "-file"', rtl_bzl)
        self.assertIn("_ut_sim_waves_template_vcs_default", rtl_bzl)
        self.assertIn('pre_fa.append("  +define+{}{}', rtl_bzl)
        self.assertIn("params['inherits'] = [_gatesim_target(inherit, corner) for inherit in inherits]", dv_bzl)


if __name__ == "__main__":
    unittest.main()
