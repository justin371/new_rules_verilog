# vim: set ft=bzl :
load("@buildifier_prebuilt//:rules.bzl", "buildifier")
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
    name = "bazel_profile_test",
    srcs = ["bazel_profile_test.py"],
    deps = ["//lib:bazel_profile"],
)

py_test(
    name = "check_test_test",
    srcs = ["check_test_test.py"],
    deps = ["//bin:check_test_lib"],
)

py_test(
    name = "cmn_logging_test",
    srcs = ["cmn_logging_test.py"],
    deps = ["//lib:cmn_logging"],
)

py_test(
    name = "compile_cache_test",
    srcs = ["compile_cache_test.py"],
    deps = ["//lib:compile_cache"],
)

py_test(
    name = "coverage_data_test",
    srcs = ["coverage_data_test.py"],
    deps = ["//lib:coverage_data"],
)

py_test(
    name = "docs_test",
    srcs = ["docs_test.py"],
    data = [
        "//:README.md",
        "//docs:defs.md",
        "//docs:eda_workflow_review.md",
        "//docs:simmer_vcs_xcelium.md",
        "//docs:simulator_migration_checklist.md",
        "//verilog:defs.bzl",
    ],
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
    name = "normalize_runfiles_flist_test",
    srcs = ["normalize_runfiles_flist_test.py"],
    deps = ["//bin:normalize_runfiles_flist_lib"],
)

py_test(
    name = "regression_discovery_test",
    srcs = ["regression_discovery_test.py"],
    deps = ["//lib:regression"],
)

py_test(
    name = "regression_report_test",
    srcs = ["regression_report_test.py"],
    data = ["//bin:regression_report_templates"],
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
