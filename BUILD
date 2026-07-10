# vim: set ft=bzl :
load("//verilog:defs.bzl", "verilog_tool_encapsulation")
load("@com_github_bazelbuild_buildtools//buildifier:def.bzl", "buildifier")
load("@buildifier_prebuilt//:rules.bzl", "buildifier", "buildifier_test")

package(default_visibility = ["//visibility:public"])

verilog_tool_encapsulation(
    name = "verilog_dv_unit_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_dv_unit_test_command_vcs",
    build_setting_default = "vcs",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_cdc_test_command",
    build_setting_default = "jg",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_lint_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_lint_test_command_vcs",
    build_setting_default = "vcs",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_unit_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_unit_test_command_vcs",
    build_setting_default = "vcs",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_svunit_test_command",
    build_setting_default = "xrun",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_wave_viewer_command",
    build_setting_default = "simvision",
)

verilog_tool_encapsulation(
    name = "verilog_rtl_wave_viewer_command_vcs",
    build_setting_default = "verdi",
)

# Can't get buildifier to report diff warnings and lint warnings in the same rule
# Throws error:
#   buildifier: lint mode warn is only compatible with --mode=fix
# Just splitting it into two different rules
BUILDIFIER_EXCLUDE = [
    "./.git/*",  # Prevent Buildifier from inserting unnecessary newlines.
    "./bazel-*/**/*",  # Omit the files under the Bazel results
]

buildifier_test(
    name = "buildifier_diff",
    diff_command = "diff -u",
    exclude_patterns = BUILDIFIER_EXCLUDE,
    mode = "diff",
    no_sandbox = True,
    verbose = True,
    workspace = "//:WORKSPACE",
)

buildifier(
    name = "buildifier_lint",
    lint_mode = "warn",
    lint_warnings = [
        "-function-docstring-args",
        "-function-docstring",
        "-module-docstring",
        "-unused-variable",
    ],
    mode = "check",
)

buildifier(
    name = "buildifier_fix",
    exclude_patterns = BUILDIFIER_EXCLUDE,
    lint_mode = "fix",
    mode = "fix",
)

# Test to ensure all Bazel build files are properly formatted.
buildifier_test(
    name = "buildifier_test",
    srcs = glob(
        [
            "**/*.bazel",
            "**/*.bzl",
            "**/*.oss",
            "**/*.sky",
            "**/BUILD",
        ],
        # Node modules do not play nice with buildifier. Exclude these
        # generated Bazel files from format testing.
        #exclude = ["**/node_modules/**/*"],
    ) + ["WORKSPACE"],
    diff_command = "diff -u",
    mode = "diff",
    verbose = True,
)
