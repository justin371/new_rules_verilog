from pathlib import Path
import os
import re
import unittest


FILELIST_FLAG_RE = re.compile(r"(?m)(^|\s)-file\s+\S+")
LEGACY_FILELIST_FLAG_RE = re.compile(r"(?m)(^|\s)-f\s+\S+")


def read_runfile(relative_path):
    test_workspace = os.environ.get("TEST_WORKSPACE", "__main__")
    manifest_file = os.environ.get("RUNFILES_MANIFEST_FILE")
    manifest_key = "{}/{}".format(test_workspace, relative_path.replace("\\", "/"))
    if manifest_file:
        for line in Path(manifest_file).read_text(encoding = "utf-8").splitlines():
            if line.startswith(manifest_key + " "):
                return Path(line.split(" ", 1)[1]).read_text(encoding = "utf-8")

    test_srcdir = os.environ["TEST_SRCDIR"]
    runfiles_root = Path(test_srcdir) / test_workspace
    path = runfiles_root / relative_path
    if path.exists():
        return path.read_text(encoding = "utf-8")

    target_name = Path(relative_path).name
    matches = []
    for candidate in runfiles_root.rglob(target_name):
        candidate_normalized = candidate.as_posix()
        if candidate_normalized.endswith(relative_path):
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0].read_text(encoding = "utf-8")
    if len(matches) > 1:
        raise AssertionError(
            "Ambiguous runfile lookup for {}: {}".format(
                relative_path,
                [str(match) for match in matches],
            )
        )
    raise AssertionError("Missing runfile: {}".format(path))


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
    def test_vcs_outputs_use_dash_file(self):
        filelist_checks = {
            "tests/vcs_filelist_validation/rtl_lint_vcs": [
                "vcs \\",
                "-file tests/vcs_filelist_validation/rtl_lint_vcs_cmds.tcl",
                "./bin/lint_parser_vcs.py",
            ],
            "tests/vcs_filelist_validation/rtl_lint_vcs_cmds.tcl": [
                "-file tests/vcs_filelist_validation/unit_test_top.f",
                "-file vendors/synopsys/verilog_rtl_lint_default_opts.f",
            ],
            "tests/vcs_filelist_validation/dv_tb_vcs_compile_args.f": [
                "-file tests/vcs_filelist_validation/unit_test_top.f",
                "+define+UNIFIED_VCS_COMPILE_ARG",
            ],
        }
        content_checks = {
            "tests/vcs_filelist_validation/dv_tb_vcs_runtime_args.f": [
                "+UNIFIED_VCS_RUNTIME_ARG",
            ],
        }

        for relative_path, needles in filelist_checks.items():
            contents = read_runfile(relative_path)
            assert_has_filelist_flag(contents, relative_path)
            assert_lacks_legacy_filelist_flag(contents, relative_path)
            for needle in needles:
                assert_contains(contents, needle, relative_path)
        for relative_path, needles in content_checks.items():
            contents = read_runfile(relative_path)
            for needle in needles:
                assert_contains(contents, needle, relative_path)


if __name__ == "__main__":
    unittest.main()
