# vim: set ft=bzl :
load("@com_github_bazelbuild_buildtools//buildifier:def.bzl", "buildifier")
load("@rules_python//python:defs.bzl", "py_test")

buildifier(
    name = "buildifier_format_diff",
    diff_command = "diff",
    mode = "diff",
)

buildifier(
    name = "buildifier_lint",
    lint_mode = "warn",
    lint_warnings = [
        "-function-docstring-args",
        "-function-docstring",
    ],
    mode = "fix",
)

py_test(
    name = "check_test_test",
    srcs = ["check_test_test.py"],
    deps = ["//bin:check_test_lib"],
)

py_test(
    name = "job_manager_launch_test",
    srcs = ["job_manager_launch_test.py"],
    deps = [
        "//lib:job_lib",
        "//lib:rv_utils",
    ],
)

py_test(
    name = "regression_discovery_test",
    srcs = ["regression_discovery_test.py"],
    deps = ["//lib:regression"],
)

py_test(
    name = "regression_report_test",
    srcs = ["regression_report_test.py"],
    deps = ["//lib:regression_report"],
)

py_test(
    name = "sim_artifacts_test",
    srcs = ["sim_artifacts_test.py"],
    deps = ["//lib:sim_artifacts"],
)

py_test(
    name = "simmer_results_test",
    srcs = ["simmer_results_test.py"],
    deps = ["//lib:simmer_results"],
)

buildifier(
    name = "buildifier_fix",
    lint_mode = "fix",
    mode = "fix",
)
