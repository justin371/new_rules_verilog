import ast
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

FILELIST_FLAG_RE = re.compile(r"(?m)(^|\s)-file\s+\S+")
LEGACY_FILELIST_FLAG_RE = re.compile(r"(?m)(^|\s)-f\s+\S+")


def find_runfile(relative_path):
    test_workspace = os.environ.get("TEST_WORKSPACE", "__main__")
    manifest_file = os.environ.get("RUNFILES_MANIFEST_FILE")
    normalized_path = relative_path.replace("\\", "/")
    manifest_key = "{}/{}".format(test_workspace, normalized_path)
    if normalized_path.startswith("external/"):
        manifest_key = normalized_path[len("external/"):]
    if manifest_file:
        for line in Path(manifest_file).read_text(encoding="utf-8").splitlines():
            if line.startswith(manifest_key + " "):
                return Path(line.split(" ", 1)[1])

    test_srcdir = os.environ["TEST_SRCDIR"]
    runfiles_root = Path(test_srcdir) / test_workspace
    if normalized_path.startswith("external/"):
        external_path = Path(test_srcdir) / normalized_path[len("external/"):]
        if external_path.exists():
            return external_path
    path = runfiles_root / relative_path
    if path.exists():
        return path

    target_name = Path(relative_path).name
    matches = []
    for candidate in runfiles_root.rglob(target_name):
        candidate_normalized = candidate.as_posix()
        if candidate_normalized.endswith(relative_path):
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AssertionError("Ambiguous runfile lookup for {}: {}".format(
            relative_path,
            [str(match) for match in matches],
        ))
    raise AssertionError("Missing runfile: {}".format(path))


def read_runfile(relative_path):
    return find_runfile(relative_path).read_text(encoding="utf-8")


def runfile_exists(relative_path):
    try:
        read_runfile(relative_path)
    except AssertionError:
        return False
    return True


def assert_contains(contents, needle, relative_path):
    if needle not in contents:
        raise AssertionError("Expected {!r} in {}".format(needle, relative_path))


def assert_has_filelist_flag(contents, relative_path):
    if not FILELIST_FLAG_RE.search(contents):
        raise AssertionError("Expected -file usage in {}".format(relative_path))


def assert_lacks_legacy_filelist_flag(contents, relative_path):
    if LEGACY_FILELIST_FLAG_RE.search(contents):
        raise AssertionError("Unexpected legacy -f usage in {}".format(relative_path))


class VcsFilelistValidationTest(unittest.TestCase):

    def test_no_synth_remains_compatible_with_simulation_analysis(self):
        filelist = read_runfile("tests/vcs_filelist_validation/no_synth_compat.f")
        self.assertIn("tests/vcs_filelist_validation/unit_test_top.sv", filelist)

    def test_makelib_is_xrun_only_and_vcs_keeps_the_source_boundary(self):
        xrun_filelist = read_runfile("tests/vcs_filelist_validation/unit_test_top.f")
        vcs_filelist = read_runfile("tests/vcs_filelist_validation/unit_test_top_vcs.f")
        dv_xrun_filelist = read_runfile("tests/vcs_filelist_validation/dv_makelib.f")
        dv_vcs_filelist = read_runfile("tests/vcs_filelist_validation/dv_makelib_vcs.f")
        vcs_compile_args = read_runfile("tests/vcs_filelist_validation/dv_tb_vcs_compile_args.f")

        self.assertIn("-makelib\nunit_test_lib\n", xrun_filelist)
        self.assertIn("-endlib", xrun_filelist)
        self.assertNotIn("-makelib", vcs_filelist)
        self.assertNotIn("-endlib", vcs_filelist)
        self.assertNotIn("unit_test_lib", vcs_filelist)
        self.assertIn("tests/vcs_filelist_validation/unit_test_top.sv", vcs_filelist)
        self.assertIn("-makelib\ndv_unit_test_lib\n", dv_xrun_filelist)
        self.assertIn("-endlib", dv_xrun_filelist)
        self.assertNotIn("-makelib", dv_vcs_filelist)
        self.assertNotIn("-endlib", dv_vcs_filelist)
        self.assertNotIn("dv_unit_test_lib", dv_vcs_filelist)
        self.assertIn("tests/vcs_filelist_validation/unit_test_top.sv", dv_vcs_filelist)
        self.assertIn("-file tests/vcs_filelist_validation/unit_test_top_vcs.f", vcs_compile_args)

    def test_dv_test_cfg_keeps_its_public_runtime_contract(self):
        dynamic_args = ast.literal_eval(read_runfile("tests/vcs_filelist_validation/dv_cfg_vcs_dynamic_args.py", ))

        self.assertEqual("VCS", dynamic_args["simulator"])
        self.assertEqual("dv_cfg_vcs", dynamic_args["uvm_testname"])
        self.assertEqual(["^PROJECT PASS$"], dynamic_args["run_pass_patterns"])
        self.assertEqual(["^PROJECT FAIL$"], dynamic_args["run_fail_patterns"])

        inherited_args = ast.literal_eval(
            read_runfile("tests/vcs_filelist_validation/dv_cfg_vcs_inherited_dynamic_args.py", ))
        self.assertEqual("VCS", inherited_args["simulator"])
        self.assertEqual("dv_cfg_vcs", inherited_args["uvm_testname"])
        self.assertEqual(17, inherited_args["timeout_minutes"])

        no_timeout_args = ast.literal_eval(
            read_runfile("tests/vcs_filelist_validation/dv_cfg_vcs_no_timeout_dynamic_args.py", ))
        self.assertEqual(0, no_timeout_args["timeout_minutes"])

    def test_vcs_outputs_use_dash_file(self):
        filelist_checks = {
            "tests/vcs_filelist_validation/rtl_lint_vcs": [
                "vcs \\",
                "-file tests/vcs_filelist_validation/rtl_lint_vcs_cmds.tcl",
                "./bin/lint_parser_vcs.py",
            ],
            "tests/vcs_filelist_validation/rtl_lint_vcs_cmds.tcl": [
                "+define+LINT",
                "-file tests/vcs_filelist_validation/unit_test_top_vcs.f",
                "-file vendors/synopsys/verilog_rtl_lint_default_opts.f",
            ],
            "tests/vcs_filelist_validation/dv_tb_vcs_compile_args.f": [
                "-file external/filelist_external_fixture/external_rtl.f",
                "-file tests/vcs_filelist_validation/unit_test_top_vcs.f",
                "+define+CADENCE_WORKAROUND",
                "+define+UNIFIED_VCS_COMPILE_ARG",
                "+define+XRUNNER",
                "+optconfigfile+tests/vcs_filelist_validation/vcs_partitions.cfg",
            ],
        }
        content_checks = {
            "tests/vcs_filelist_validation/dv_tb_vcs_runtime_args.f": [
                "+UNIFIED_VCS_RUNTIME_ARG",
                "-f bazel_runfiles_main/tests/vcs_filelist_validation/vcs_partitions.cfg",
            ],
        }

        for relative_path, needles in filelist_checks.items():
            contents = read_runfile(relative_path)
            self.assertNotIn("../", contents, relative_path)
            assert_has_filelist_flag(contents, relative_path)
            assert_lacks_legacy_filelist_flag(contents, relative_path)
            for needle in needles:
                assert_contains(contents, needle, relative_path)
        for relative_path, needles in content_checks.items():
            contents = read_runfile(relative_path)
            for needle in needles:
                assert_contains(contents, needle, relative_path)

        self.assertFalse(runfile_exists("tests/vcs_filelist_validation/dv_tb_vcs_compile_args_pldm_ice.f"))
        self.assertFalse(runfile_exists("tests/vcs_filelist_validation/dv_tb_vcs_compile_args_pldm_sa.f"))

        external_flist = read_runfile("external/filelist_external_fixture/external_rtl.f")
        self.assertIn("external/filelist_external_fixture/external_ip.sv", external_flist)
        self.assertNotIn("../", external_flist)
        self.assertNotIn("+define+CADENCE\n", read_runfile("tests/vcs_filelist_validation/dv_tb_vcs_compile_args.f"))

    def test_xcelium_tb_coverage_file_is_in_compile_args(self):
        compile_args = read_runfile("tests/vcs_filelist_validation/dv_tb_xrun_ccf_compile_args.f")
        tb_options = ast.literal_eval(read_runfile("tests/vcs_filelist_validation/dv_tb_xrun_ccf_tb_options.py"))

        self.assertNotIn("-covfile", compile_args)
        self.assertEqual("tests/vcs_filelist_validation/coverage.ccf", tb_options["xcelium_covfile"])

        vcs_options = ast.literal_eval(read_runfile("tests/vcs_filelist_validation/dv_tb_vcs_tb_options.py"))
        self.assertEqual("tests/vcs_filelist_validation/coverage_hier.cfg", vcs_options["vcs_cm_hier"])
        self.assertNotIn("xcelium_covfile", vcs_options)
        self.assertNotIn("msie_primary_compile_args", vcs_options)
        self.assertNotIn("msie_incremental_compile_args", vcs_options)
        self.assertNotIn("msie_primary_inputs", vcs_options)

        compile_inputs = read_runfile(vcs_options["compile_inputs"])
        self.assertIn("source\ttests/vcs_filelist_validation/unit_test_top.sv", compile_inputs)
        self.assertIn("source\texternal/filelist_external_fixture/external_ip.sv", compile_inputs)
        self.assertIn("filelist\ttests/vcs_filelist_validation/unit_test_top_vcs.f", compile_inputs)
        self.assertNotIn("filelist\ttests/vcs_filelist_validation/unit_test_top.f\n", compile_inputs)
        self.assertIn("runfile\ttests/vcs_filelist_validation/coverage_hier.cfg", compile_inputs)

    def test_xcelium_msie_filelists_are_bazel_generated_and_partitioned(self):
        primary_path = "tests/vcs_filelist_validation/dv_tb_xrun_ccf_msie_primary_compile_args.f"
        incremental_path = "tests/vcs_filelist_validation/dv_tb_xrun_ccf_msie_incremental_compile_args.f"
        inputs_path = "tests/vcs_filelist_validation/dv_tb_xrun_ccf_msie_primary_inputs.txt"
        primary = read_runfile(primary_path)
        incremental = read_runfile(incremental_path)
        inputs = read_runfile(inputs_path)
        tb_options = ast.literal_eval(read_runfile("tests/vcs_filelist_validation/dv_tb_xrun_ccf_tb_options.py"))

        self.assertIn("-define MSIE_PRIMARY", primary)
        self.assertIn("-covfile tests/vcs_filelist_validation/coverage.ccf", primary)
        self.assertIn("-f tests/vcs_filelist_validation/unit_test_top.f", primary)
        self.assertNotIn("MSIE_INCREMENTAL", primary)
        self.assertIn("-define MSIE_INCREMENTAL", incremental)
        self.assertIn("-f external/filelist_external_fixture/external_rtl.f", incremental)
        self.assertIn("source\ttests/vcs_filelist_validation/unit_test_top.sv", inputs)
        self.assertIn("filelist\ttests/vcs_filelist_validation/unit_test_top.f", inputs)
        self.assertNotIn("filelist\ttests/vcs_filelist_validation/unit_test_top_vcs.f", inputs)
        self.assertIn("runfile\ttests/vcs_filelist_validation/coverage.ccf", inputs)
        self.assertEqual(primary_path, tb_options["msie_primary_compile_args"])
        self.assertEqual(incremental_path, tb_options["msie_incremental_compile_args"])
        self.assertEqual(inputs_path, tb_options["msie_primary_inputs"])
        self.assertNotIn("vcs_cm_hier", tb_options)

    def test_unit_test_scripts_use_xcelium(self):
        scripts = {
            "tests/vcs_filelist_validation/dv_unit_xrun_run.sh": ["xrun", "-f"],
            "tests/vcs_filelist_validation/rtl_unit_xrun": ["xrun", "-f", "waves.shm"],
        }
        for relative_path, needles in scripts.items():
            contents = read_runfile(relative_path)
            for needle in needles:
                assert_contains(contents, needle, relative_path)

    def test_rtl_unit_test_propagates_data_target_runfiles(self):
        self.assertEqual(
            "runtime tool data\n",
            read_runfile("tests/vcs_filelist_validation/runtime_tool.data"),
        )

    def test_generated_unit_test_scripts_execute_with_tool_stubs(self):
        tool_stub = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

tool = Path(sys.argv[0]).name
with open(os.environ["TOOL_LOG"], "a", encoding="utf-8") as log_file:
    log_file.write(json.dumps({"tool": tool, "args": sys.argv[1:]}) + "\\n")
"""

        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_path = Path(temporary_dir)
            bin_dir = temporary_path / "bin"
            bin_dir.mkdir()
            for tool in ("runmod", ):
                tool_path = bin_dir / tool
                tool_path.write_text(tool_stub, encoding="utf-8")
                tool_path.chmod(0o755)

            log_path = temporary_path / "tools.jsonl"
            environment = dict(os.environ)
            environment.update({
                "PATH": "{}{}{}".format(bin_dir, os.pathsep, environment["PATH"]),
                "TOOL_LOG": str(log_path),
            })
            invocations = {
                "tests/vcs_filelist_validation/dv_unit_xrun_run.sh": [],
                "tests/vcs_filelist_validation/rtl_unit_xrun": ["--waves"],
            }
            for index, (relative_path, arguments) in enumerate(invocations.items()):
                working_dir = temporary_path / "run_{}".format(index)
                working_dir.mkdir()
                subprocess.run(
                    ["bash", str(find_runfile(relative_path))] + arguments,
                    cwd=working_dir,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(record["tool"] == "runmod" for record in records))
            for record in records:
                self.assertFalse(any(not argument.strip() for argument in record["args"]), record)

    def test_generated_script_reports_failed_command(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            bin_dir = Path(temporary_dir) / "bin"
            bin_dir.mkdir()
            runmod_path = bin_dir / "runmod"
            runmod_path.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
            runmod_path.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = "{}{}{}".format(bin_dir, os.pathsep, environment["PATH"])

            result = subprocess.run(
                ["bash", str(find_runfile("tests/vcs_filelist_validation/dv_unit_xrun_run.sh"))],
                cwd=temporary_dir,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(23, result.returncode)
            self.assertIn("ERROR: line", result.stderr)
            self.assertIn("exited 23", result.stderr)
            self.assertIn("runmod", result.stderr)


if __name__ == "__main__":
    unittest.main()
