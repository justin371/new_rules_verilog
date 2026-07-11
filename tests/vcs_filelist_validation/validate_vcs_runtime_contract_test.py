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
LIB_DIR = REPO_ROOT / "lib"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from args_parser import parse_args
from args_parse.parser import create_parser
from lint_parser_hal import HalLintLog
from lib.job_lib import JobStatus
from lib.runtime_options import format_sim_opts_dict, resolve_test_timeout_hours
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
        self.job_dir = tempfile.mkdtemp(prefix="vcs_vcomp_")
        self.name = "unit_vcomp"
        self.tb_options = {
            "dut_instance": "hdl_top.dut",
            "dut_top": "unit_test_top",
            "vcs_cm_hier": "tests/coverage_hier.cfg",
            "xcelium_covfile": "tests/coverage.ccf",
        }


class VcsRuntimeContractTest(unittest.TestCase):

    def test_simmer_help_documents_every_option_and_critical_preparation(self):
        parser = create_parser()
        for action in parser._actions:
            if not action.option_strings:
                continue
            self.assertIsInstance(action.help, str, action.option_strings)
            self.assertGreaterEqual(len(action.help.strip()), 20, action.option_strings)

        help_text = parser.format_help()
        self.assertIn("Bazel 7.7.1, Python 3.12", help_text)
        self.assertIn("Quote all test globs", help_text)
        self.assertIn("default: adaptive", help_text)
        self.assertIn("must already exist", help_text)
        self.assertIn("custom external partcomp/sharedlib directories are preserved", help_text)
        self.assertIn("Run this before --msie-prim", help_text)
        self.assertIn("Requires EMU_JINJA2_PATH", help_text)

    def test_zero_test_timeout_disables_job_timeout(self):
        self.assertEqual(0, resolve_test_timeout_hours({"timeout_minutes": 0}, 12.0, False))

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

    def test_xprop_is_opt_in_for_both_simulators(self):
        vcs_options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        xcelium_options = parse_args(["-t", "unit:test", "--simulator", "XRUN"])

        self.assertIsNone(vcs_options.xprop)
        self.assertFalse(vcs_options.xprop_was_explicit)
        self.assertIsNone(xcelium_options.xprop)

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

    def test_simulator_adapters_report_scheduler_thread_cost(self):
        vcs_options = parse_args(["--simulator", "VCS", "--fgp", "4"])
        xrun_options = parse_args(["--simulator", "XRUN", "--mce", "--mce-sim-count", "3"])

        self.assertEqual(4, VcsSimulator(vcs_options, DummyRegressionConfig(), None).get_scheduler_threads_per_test())
        self.assertEqual(3, XceliumSimulator(xrun_options, DummyRegressionConfig(), None).get_scheduler_threads_per_test())

    def test_vcs_adapter_validates_vso_environment(self):
        options = parse_args(["--simulator", "VCS", "--vso", "--cm", "line"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "VSO_HOME is not set"):
                simulator.validate_run_options(1)

    def test_simmer_dispatches_backend_validation_and_scheduler_capabilities(self):
        simmer_source = self._read_repo_file("bin/simmer.py")

        self.assertIn("simulator.validate_resolved_options()", simmer_source)
        self.assertIn("simulator.validate_run_options(len(rcfg.all_vcomp))", simmer_source)
        self.assertIn("simulator.get_scheduler_threads_per_test()", simmer_source)
        self.assertNotIn('options.simulator == "VCS"', simmer_source)
        self.assertNotIn('options.simulator == "XRUN"', simmer_source)

    def test_simulator_adapters_reject_opposite_backend_switches(self):
        vcs_options = parse_args(["--simulator", "VCS"])
        vcs_options.xcelium_explicit_switches = ["--mce"]
        with self.assertRaisesRegex(ValueError, "Xcelium-only"):
            VcsSimulator(vcs_options, DummyRegressionConfig(), None).validate_resolved_options()

        xrun_options = parse_args(["--simulator", "XRUN"])
        xrun_options.vcs_explicit_switches = ["--fgp"]
        with self.assertRaisesRegex(ValueError, "VCS-only"):
            XceliumSimulator(xrun_options, DummyRegressionConfig(), None).validate_resolved_options()

    def test_iterations_are_preplanned_for_parallel_execution(self):
        simmer_source = self._read_repo_file("bin/simmer.py")

        self.assertEqual("0", parse_args(["--python-seed", "0"]).python_seed)
        self.assertIn("range(1, iterations + 1)", simmer_source)
        self.assertIn("if options.vso and self.icfg.spawn_count <= self.icfg.target:", simmer_source)
        self.assertNotIn("random.seed(options.python_seed)", simmer_source)

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

    def test_vcs_partition_compile_defaults_to_vcomp_owned_database(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        vcomp = DummyVcompJob()

        partcomp_args = shlex.split(simulator.generate_compile_options(vcomp)["partcomp_opts"])

        self.assertIn("-partcomp=adaptive_sched", partcomp_args)
        self.assertIn("-partcomp_dir={}".format(os.path.join(vcomp.job_dir, "partitionlib")), partcomp_args)
        self.assertIn("-partcomp=incr_clean", partcomp_args)
        self.assertIn("-fastpartcomp=j8", partcomp_args)

    def test_vcs_partition_compile_supports_external_shared_database(self):
        sharedlib = tempfile.mkdtemp(prefix="shared partition ")
        writable = os.path.join(tempfile.mkdtemp(prefix="writable parent "), "partition database")
        options = parse_args([
            "-t",
            "unit:test",
            "--simulator",
            "VCS",
            "--vcs-partcomp-mode",
            "high",
            "--vcs-partcomp-jobs",
            "4",
            "--vcs-partcomp-dir",
            writable,
            "--vcs-partcomp-sharedlib",
            sharedlib,
        ])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)

        partcomp_args = shlex.split(simulator.generate_compile_options(DummyVcompJob())["partcomp_opts"])

        self.assertIn("-partcomp=autopart_high", partcomp_args)
        self.assertIn("-partcomp_dir={}".format(writable), partcomp_args)
        self.assertIn("-partcomp_sharedlib={}".format(sharedlib), partcomp_args)
        self.assertIn("-fastpartcomp=j4", partcomp_args)

    def test_vcs_partition_compile_rejects_invalid_configuration(self):
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "VCS", "--vcs-partcomp-jobs", "0"])
        with self.assertRaises(SystemExit):
            parse_args([
                "--simulator",
                "VCS",
                "--vcs-partcomp-mode",
                "disabled",
                "--vcs-partcomp-dir",
                "/tmp/partcomp",
            ])
        sharedlib = tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            parse_args([
                "--simulator",
                "VCS",
                "--vcs-partcomp-dir",
                sharedlib,
                "--vcs-partcomp-sharedlib",
                sharedlib,
            ])

    def test_vcs_partition_compile_can_be_disabled_for_comparison(self):
        options = parse_args(["--simulator", "VCS", "--vcs-partcomp-mode", "disabled"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)

        self.assertEqual("", simulator.generate_compile_options(DummyVcompJob())["partcomp_opts"])

    def test_vcs_dtl_uses_required_partition_compile_flow(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--dtl"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        vcomp = DummyVcompJob()

        partcomp_args = shlex.split(simulator.generate_compile_options(vcomp)["partcomp_opts"])

        self.assertEqual("-partcomp", partcomp_args[0])
        self.assertIn("-dir={}".format(os.path.join(vcomp.job_dir, "dtl_static")), partcomp_args)
        self.assertIn("-fastpartcomp=j8", partcomp_args)

    def test_smartlog_is_vcs_only_and_simmer_profile_is_common(self):
        self.assertTrue(parse_args(["-t", "unit:test", "--simulator", "XRUN", "--simmer-profile"]).simmer_profile)
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "XRUN", "--smartlog"])
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "XRUN", "--vcs-partcomp-jobs", "4"])
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "XRUN", "--vcs-partcomp-mode", "adaptive"])

    def test_tool_specific_arguments_are_rejected_by_the_other_backend(self):
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "VCS", "--probe-packed", "64"])
        with self.assertRaises(SystemExit):
            parse_args(["-t", "unit:test", "--simulator", "VCS", "--probe-packed", "128"])
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
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--wave-delta"])
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--waves", "--wave-type", "vwdb", "--wave-delta"])

    def test_xcelium_msie_incremental_requires_primary_snapshot_name(self):
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--msie-incr"])
        self.assertEqual("pcie_primary", parse_args(["--simulator", "XRUN", "--msie-incr", "pcie_primary"]).msie_incr)

        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--msie-prim"])
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--msie-primary-name", "snapshot"])

    def test_xcelium_msie_template_separates_primary_top_and_snapshot(self):
        template = jinja2.Template(
            self._read_repo_file("bin/templates/xrun_compile_template.sh.j2"),
            undefined=jinja2.StrictUndefined,
        )
        rendered = template.render(
            VCOMP_DIR="/results/sys__XRUN_VCOMP_PRIM",
            additional_defines=[],
            bazel_compile_args="/runfiles/sys_msie_primary_compile_args.f",
            bazel_runfiles_main="/runfiles",
            cov_opts="",
            debug_mode="default",
            msie_extern_files=["/results/sys__XRUN_VCOMP_MSIE/dut_externs.v"],
            msie_href_file="/results/sys__XRUN_VCOMP_MSIE/href.txt",
            msie_primary_dir="/results/sys__XRUN_VCOMP_PRIM",
            msie_primary_name="dut_sdf_wc",
            msie_primary_top="dut",
            options=SimpleNamespace(
                compile_args_file=None,
                mce=False,
                msie=None,
                msie_href=None,
                msie_incr=None,
                msie_prim="dut",
            ),
            xprop_cmd=None,
        )

        self.assertIn("-top dut -snapshot dut_sdf_wc", rendered)
        self.assertNotIn("-name dut", rendered)
        self.assertIn("dut_externs.v", rendered)
        self.assertNotIn("incr_pkg", rendered)

    def test_xcelium_msie_manifest_rejects_wrong_primary_key(self):
        root = Path(tempfile.mkdtemp(prefix="xrun_msie_"))
        runfiles = root / "runfiles"
        (runfiles / "tb").mkdir(parents=True)
        (runfiles / "tb/dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        (runfiles / "tb/sys_msie_primary_compile_args.f").write_text("tb/dut.sv\n", encoding="utf-8")
        (runfiles / "tb/sys_msie_incremental_compile_args.f").write_text("tb/test.sv\n", encoding="utf-8")
        (runfiles / "tb/sys_msie_primary_inputs.txt").write_text("source\ttb/dut.sv\n", encoding="utf-8")
        base_job_dir = str(root / "sys__XRUN_VCOMP")
        artifact_dir = Path(base_job_dir + "_MSIE")
        artifact_dir.mkdir()
        (artifact_dir / "href.txt").write_text("@dut *\n", encoding="utf-8")
        tb_options = {
            "dut_top": "dut",
            "msie_incremental_compile_args": "tb/sys_msie_incremental_compile_args.f",
            "msie_primary_compile_args": "tb/sys_msie_primary_compile_args.f",
            "msie_primary_inputs": "tb/sys_msie_primary_inputs.txt",
            "xcelium_covfile": "",
        }

        def vcomp():
            return SimpleNamespace(
                base_job_dir=base_job_dir,
                bazel_compile_args=str(runfiles / "tb/sys_compile_args.f"),
                bazel_runfiles_main=str(runfiles),
                bazel_vcomp_target="//tb:sys",
                tb_options=tb_options,
            )

        primary_options = parse_args([
            "--simulator",
            "XRUN",
            "--msie-prim",
            "dut",
            "--msie-primary-name",
            "dut_sdf_wc",
            "--msie-primary-key",
            "XCELIUM-25.03:netlist-r42:sdf_wc",
        ])
        primary = XceliumSimulator(primary_options, DummyRegressionConfig(), None)
        primary_vcomp = vcomp()
        primary.prepare_compile_job(primary_vcomp)
        Path(primary_vcomp.msie_primary_dir).mkdir()
        primary.record_compile_artifacts(primary_vcomp)

        incremental_options = parse_args([
            "--simulator",
            "XRUN",
            "--msie-incr",
            "dut_sdf_wc",
            "--msie-primary-key",
            "XCELIUM-25.03:netlist-r42:sdf_wc",
        ])
        incremental = XceliumSimulator(incremental_options, DummyRegressionConfig(), None)
        incremental.prepare_compile_job(vcomp())

        wrong_key_options = parse_args([
            "--simulator",
            "XRUN",
            "--msie-incr",
            "dut_sdf_wc",
            "--msie-primary-key",
            "XCELIUM-25.03:netlist-r43:sdf_wc",
        ])
        with self.assertRaisesRegex(RuntimeError, "primary_key"):
            XceliumSimulator(wrong_key_options, DummyRegressionConfig(), None).prepare_compile_job(vcomp())

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
        vcs_compile = self._read_repo_file("bin/templates/vcs_compile_template.sh.j2")
        sim = self._read_repo_file("bin/templates/sim_template.sh.j2")
        svunit = self._read_repo_file("vendors/cadence/verilog_rtl_unit_test_svunit.sh.template")
        cdc = self._read_repo_file("vendors/cadence/verilog_rtl_cdc_test.sh.template")
        lint_templates = [
            self._read_repo_file("vendors/cadence/verilog_rtl_lint_test.sh.template"),
            self._read_repo_file("vendors/synopsys/verilog_rtl_lint_test.sh.template"),
            self._read_repo_file("vendors/real_intent/verilog_rtl_lint_test.sh.template"),
        ]

        self.assertIn("set -Eeuo pipefail", coverage)
        self.assertIn("set -Eeuo pipefail", vcs_compile)
        self.assertIn("VCS compile failed at line", vcs_compile)
        self.assertIn("simulation script failed at line", sim)
        self.assertNotIn("final_result + sim_exit_code", sim)
        self.assertNotIn("sockets_exit_code + socket_exit_code", sim)
        self.assertNotIn('time eval "{{ simulation_command }}"', sim)
        self.assertIn("time {{ simulation_command }}", sim)
        self.assertIn('kill "${{ socket_name|upper }}_PID"', sim)
        self.assertIn('kill -KILL "$current_pid"', sim)
        self.assertIn("{POST_FLIST_ARGS} \\", svunit)
        self.assertIn('"${remaining_args[@]}"', svunit)
        self.assertIn("completed without cdc_run/jg.log", cdc)
        for template in lint_templates:
            self.assertIn("set -Eeuo pipefail", template)
            self.assertIn('"$@"', template)
        self.assertIn('"${PYTHON:-python3}" ./{LINT_PARSER}', lint_templates[1])

    def test_vcs_compile_template_defaults_to_incremental_compile(self):
        template = self._read_repo_file("bin/templates/vcs_compile_template.sh.j2")
        compile_args = self._read_repo_file("vendors/synopsys/verilog_dv_tb_compile_args.f.template")

        self.assertIn("mkdir -p {{ VCOMP_DIR }}/csrc", template)
        self.assertIn("-Mdir={{ VCOMP_DIR }}/csrc", template)
        self.assertIn("-Mlib={{ VCOMP_DIR }}/csrc", template)
        self.assertIn("{{ partcomp_opts }}", template)
        self.assertNotIn("-partcomp", compile_args)
        self.assertIn("-Mupdate", compile_args)

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
        options = parse_args(["-t", "unit:test", "--simulator", "XRUN", "--waves", "--xprop", "F"])
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

        Path(vcomp.bench_dir, "fox_xprop.txt").unlink()
        self.assertEqual("-xprop F -xverbose", simulator.generate_compile_options(vcomp)["xprop_cmd"])

    def test_xcelium_coverage_uses_explicit_ccf_and_unique_base_runs(self):
        with tempfile.NamedTemporaryFile() as covfile:
            options = parse_args([
                "-t",
                "unit:test",
                "--simulator",
                "XRUN",
                "--coverage",
                "A",
                "--covfile",
                covfile.name,
            ])
            simulator = XceliumSimulator(options, DummyRegressionConfig(), None)
            compile_args = shlex.split(simulator.generate_compile_options(DummyVcompJob())["cov_opts"])

        self.assertIn("-coverage", compile_args)
        self.assertEqual("unit_test_top", compile_args[compile_args.index("-covdut") + 1])
        self.assertIn("-covfile", compile_args)
        self.assertIn(covfile.name, compile_args)

        test_job = SimpleNamespace(
            iteration=2,
            name="same_test",
            vcomper=SimpleNamespace(cov_work_dir="/tmp/cov", name="unit_vcomp"),
        )
        sim_args = shlex.split(simulator.generate_sim_options(test_job, 42))
        self.assertEqual("same_test_sv42_i2", sim_args[sim_args.index("-covbaserun") + 1])
        Path(test_job.coverage_db_path).mkdir(parents=True)
        simulator.cleanup_test_coverage(test_job)
        self.assertFalse(Path(test_job.coverage_db_path).exists())

    def test_xcelium_coverage_report_command_preserves_paths_with_spaces(self):
        options = parse_args(["--simulator", "XRUN", "--coverage", "A"])
        simulator = XceliumSimulator(options, DummyRegressionConfig(), None)
        merged_coverage_dir = tempfile.mkdtemp(prefix="merged coverage ")
        job = SimpleNamespace(
            coverage_report_tcl="/tmp/path with spaces/imc_report.tcl",
            coverage_code_report="/tmp/code.txt",
            coverage_functional_report="/tmp/functional.txt",
            merged_coverage_dir=merged_coverage_dir,
        )
        failed = SimpleNamespace(returncode=1, stderr="failed")

        with mock.patch("lib.simulators.xcelium.subprocess.run", return_value=failed) as run:
            coverage = simulator.collect_coverage_data({"//pkg:sys_tb": job})

        run.assert_called_once_with(
            ["runmod", "xrun", "--", "imc", "-exec", job.coverage_report_tcl, "-verbose"],
            capture_output=True,
            text=True,
        )
        self.assertEqual({"sys_tb": {
            "total": None,
            "vendor_score": None,
            "cc": {},
            "cf": {},
        }}, coverage)

    def test_xcelium_missing_merged_coverage_returns_empty_metrics(self):
        options = parse_args(["--simulator", "XRUN", "--coverage", "A"])
        simulator = XceliumSimulator(options, DummyRegressionConfig(), None)
        job = SimpleNamespace(coverage_report_tcl="/tmp/imc_report.tcl", merged_coverage_dir="/missing")

        with mock.patch("lib.simulators.xcelium.subprocess.run") as run:
            coverage = simulator.collect_coverage_data({"//pkg:sys_tb": job})

        run.assert_not_called()
        self.assertEqual({"sys_tb": {
            "total": None,
            "vendor_score": None,
            "cc": {},
            "cf": {},
        }}, coverage)

    def test_xcelium_dashboard_combines_code_and_functional_reports(self):
        options = parse_args(["--simulator", "XRUN", "--coverage", "A"])
        simulator = XceliumSimulator(options, DummyRegressionConfig(), None)
        report_dir = Path(tempfile.mkdtemp())
        code_report = report_dir / "coverage_code.txt"
        functional_report = report_dir / "coverage_functional.txt"
        code_report.write_text(
            "Metric Overall Block Statement Branch Expression FSM Toggle Assertion\n"
            "Cumulative 82.00 1.00 80.00 60.00 70.00 100.00 90.00 95.00\n",
            encoding="utf-8",
        )
        functional_report.write_text(
            "Metric Overall CoverGroup\n"
            "Cumulative 76.00 76.00\n",
            encoding="utf-8",
        )
        job = SimpleNamespace(
            coverage_report_tcl=str(report_dir / "imc_report.tcl"),
            coverage_code_report=str(code_report),
            coverage_functional_report=str(functional_report),
            merged_coverage_dir=str(report_dir),
        )

        with mock.patch("lib.simulators.xcelium.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            coverage = simulator.collect_coverage_data({"//pkg:sys_tb": job})["sys_tb"]

        self.assertEqual("80.00%", coverage["cc"]["Overall"])
        self.assertEqual("83.67%", coverage["total"])
        self.assertEqual("82.00%", coverage["vendor_score"])
        self.assertEqual("76.00%", coverage["cf"]["Overall"])

    def test_xcelium_coverage_and_mce_details_are_validated(self):
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--covfile", "/missing/coverage.ccf"])
        with self.assertRaises(SystemExit):
            parse_args([
                "--simulator",
                "XRUN",
                "--coverage",
                "A",
                "--covfile",
                "/missing/coverage.ccf",
            ])
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "XRUN", "--mce-sim-count", "4"])

    def test_hal_empty_direct_waiver_does_not_match_every_message(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml") as logfile:
            logfile.write("<messages></messages>")
            logfile.flush()

            self.assertIsNone(HalLintLog(logfile.name, None).waiver_direct_regex)
            self.assertIsNone(HalLintLog(logfile.name, "").waiver_direct_regex)

    def test_vso_unselected_tests_are_skipped(self):
        options = parse_args(["--simulator", "VCS", "--vso", "--cm", "line"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        icfg = SimpleNamespace(target=1, vso_assignments=[])
        test = SimpleNamespace(
            jobstatus=JobStatus.NOT_STARTED,
            target="//unit:test",
            vcomper=SimpleNamespace(name="unit_vcomp"),
        )

        with tempfile.NamedTemporaryFile(mode="w") as ask_log:
            result = simulator.apply_vso_ask_results({"//unit:tb": ([icfg], [test])}, ask_log.name)

        self.assertEqual(0, result["planned_runs"])
        self.assertEqual(JobStatus.SKIPPED, test.jobstatus)

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

    def test_vcs_failed_coverage_merge_does_not_abort_report_generation(self):
        options = parse_args(["-t", "unit:test", "--simulator", "VCS", "--cm", "line"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        vcomp = SimpleNamespace(coverage_merge_script="/tmp/unit_vcs_cov_merge.sh")

        with mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=1, stdout="", stderr="failed")):
            simulator.run_report_coverage_merge({"//unit:tb": vcomp})

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
        self.assertIn("-cm_hier tests/coverage_hier.cfg", compile_options["cov_opts"])

        template = self._read_repo_file("bin/templates/vcs_cov_merge_template.sh.j2")
        self.assertIn("{{ urg_command }}", template)
        self.assertIn("{{ verdi_command }}", template)

    def test_vcs_coverage_names_include_iteration_and_failed_db_can_be_removed(self):
        options = parse_args(["--simulator", "VCS", "--cm", "line"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        coverage_root = tempfile.mkdtemp()
        test_job = SimpleNamespace(
            iteration=3,
            name="same_test",
            vcomper=SimpleNamespace(cov_work_dir=coverage_root),
        )

        sim_args = shlex.split(simulator.generate_sim_options(test_job, 42))

        self.assertEqual("same_test_sv42_i3", sim_args[sim_args.index("-cm_name") + 1])
        Path(test_job.coverage_db_path).mkdir(parents=True)
        simulator.cleanup_test_coverage(test_job)
        self.assertFalse(Path(test_job.coverage_db_path).exists())

    def test_vcs_dashboard_reads_urg_text_report(self):
        options = parse_args(["--simulator", "VCS", "--cm", "line"])
        simulator = VcsSimulator(options, DummyRegressionConfig(), None)
        report_dir = Path(tempfile.mkdtemp())
        (report_dir / "dashboard.txt").write_text(
            "SCORE LINE COND TOGGLE FSM BRANCH ASSERT GROUP\n"
            "87.50 90.00 80.00 70.00 100.00 85.00 95.00 76.00\n",
            encoding="utf-8",
        )

        coverage = simulator.collect_coverage_data(
            {"//pkg:sys_tb": SimpleNamespace(coverage_report_dir=str(report_dir))})

        self.assertEqual("85.00%", coverage["sys_tb"]["cc"]["Overall"])
        self.assertEqual("85.33%", coverage["sys_tb"]["total"])
        self.assertEqual("87.50%", coverage["sys_tb"]["vendor_score"])
        self.assertEqual("76.00%", coverage["sys_tb"]["cf"]["Overall"])

    def test_rerun_preserves_original_options_without_forcing_waves(self):
        template = self._read_repo_file("bin/templates/rerun_template.sh.j2")

        self.assertIn("{{ reproduce_args }}", template)
        self.assertIn("{{ rerun_target }}", template)
        self.assertIn("SIMMER_KEEP_TERMINAL", template)
        self.assertNotIn('exec "$SIMMER_BIN"', template)
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
        pldm_backend = self._read_repo_file("verilog/private/simulators/pldm.bzl")
        vcs_backend = self._read_repo_file("verilog/private/simulators/vcs.bzl")
        xcelium_backend = self._read_repo_file("verilog/private/simulators/xcelium.bzl")
        vcs_python = self._read_repo_file("lib/simulators/vcs.py")
        xcelium_python = self._read_repo_file("lib/simulators/xcelium.py")
        rtl_bzl = self._read_repo_file("verilog/private/rtl.bzl")

        self.assertIn("vcs_dv_backend", dv_bzl)
        self.assertIn("xcelium_dv_backend", dv_bzl)
        self.assertNotIn('filelist_flag = "-file"', dv_bzl)
        self.assertIn('filelist_flag = "-file"', vcs_backend)
        self.assertIn("_ut_sim_template_vcs_default", vcs_backend)
        self.assertNotIn("simulators/xcelium.bzl", vcs_backend)
        self.assertNotIn("simulators/vcs.bzl", xcelium_backend)
        self.assertNotIn("xcelium_options", vcs_python)
        self.assertNotIn("vcs_options", xcelium_python)
        self.assertIn("compile_args_pldm_ice", pldm_backend)
        self.assertIn("expand_msie_compile_args", xcelium_backend)
        self.assertIn('filelist_flag = "-file"', rtl_bzl)
        self.assertIn("_ut_sim_waves_template_vcs_default", rtl_bzl)
        self.assertIn('pre_fa.append("  +define+{}{}', rtl_bzl)
        self.assertIn('defines.extend(["+define+{}{}', rtl_bzl)
        self.assertNotIn('defines.extend(["+{}{}', rtl_bzl)
        self.assertIn("[_gatesim_target(inherit, corner) for inherit in inherits]", dv_bzl)
        self.assertIn("sets no_synth=True, but rules_verilog has no synthesis consumer", rtl_bzl)
        self.assertNotIn("        no_synth = True,", rtl_bzl)
        self.assertNotIn('"_runtime_args_template"', dv_bzl)


if __name__ == "__main__":
    unittest.main()
