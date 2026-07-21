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
    name = "args_parser_validation_test",
    timeout = "short",
    srcs = ["args_parser_validation_test.py"],
    deps = ["//bin:args_parser_lib"],
)

py_test(
    name = "bazel_profile_test",
    timeout = "short",
    srcs = ["bazel_profile_test.py"],
    deps = ["//lib:bazel_profile"],
)

py_test(
    name = "check_test_test",
    timeout = "short",
    srcs = ["check_test_test.py"],
    deps = ["//bin:check_test_lib"],
)

py_test(
    name = "cmn_logging_test",
    timeout = "short",
    srcs = ["cmn_logging_test.py"],
    deps = ["//lib:cmn_logging"],
)

py_test(
    name = "compile_cache_test",
    timeout = "short",
    srcs = ["compile_cache_test.py"],
    deps = ["//lib:compile_cache"],
)

py_test(
    name = "coverage_data_test",
    timeout = "short",
    srcs = ["coverage_data_test.py"],
    deps = ["//lib:coverage_data"],
)

py_test(
    name = "docs_test",
    timeout = "short",
    srcs = ["docs_test.py"],
    data = [
        "//:README.md",
        "//docs:defs.md",
        "//docs:eda_workflow_review.md",
        "//docs:etx_self_hosted_runner.md",
        "//docs:examples/vcs_fsdb_dump.tcl",
        "//docs:simmer_vcs_xcelium.md",
        "//docs:simulator_migration_checklist.md",
        "//verilog:defs.bzl",
        "//verilog/private:dv.bzl",
    ],
)

py_test(
    name = "external_python_deps_test",
    timeout = "short",
    srcs = ["external_python_deps_test.py"],
    data = [
        "//:WORKSPACE",
        "//bin:BUILD",
        "//lib:BUILD",
        "//lib/simulators:BUILD",
    ],
)

py_test(
    name = "job_manager_launch_test",
    timeout = "short",
    srcs = ["job_manager_launch_test.py"],
    deps = [
        "//lib:job_lib",
        "//lib:rv_utils",
    ],
)

py_test(
    name = "normalize_runfiles_flist_test",
    timeout = "short",
    srcs = ["normalize_runfiles_flist_test.py"],
    deps = ["//bin:normalize_runfiles_flist_lib"],
)

py_test(
    name = "regression_discovery_test",
    timeout = "short",
    srcs = ["regression_discovery_test.py"],
    deps = ["//lib:regression"],
)

py_test(
    name = "regression_report_test",
    timeout = "short",
    srcs = ["regression_report_test.py"],
    data = ["//bin:regression_report_templates"],
    deps = ["//lib:regression_report"],
)

py_test(
    name = "runtime_options_test",
    timeout = "short",
    srcs = ["runtime_options_test.py"],
    deps = ["//lib:runtime_options"],
)

py_test(
    name = "seed_plan_test",
    timeout = "short",
    srcs = ["seed_plan_test.py"],
    deps = ["//lib:seed_plan"],
)

py_test(
    name = "sim_artifacts_test",
    timeout = "short",
    srcs = ["sim_artifacts_test.py"],
    deps = ["//lib:sim_artifacts"],
)

py_test(
    name = "simmer_results_test",
    timeout = "short",
    srcs = ["simmer_results_test.py"],
    deps = ["//lib:simmer_results"],
)

py_test(
    name = "simmer_runtime_hardening_test",
    timeout = "short",
    srcs = ["simmer_runtime_hardening_test.py"],
    data = ["//bin:simmer.py"],
    deps = [
        "//bin:args_parser_lib",
        "//bin:check_test_lib",
        "//lib:cmn_logging",
        "//lib:compile_cache",
        "//lib:job_lib",
        "//lib:parser_actions",
        "//lib:regression",
        "//lib:regression_report",
        "//lib:runtime_options",
        "//lib:rv_utils",
        "//lib:seed_plan",
        "//lib:sim_artifacts",
        "//lib:simmer_results",
        "//lib/simulators",
    ],
)

py_test(
    name = "simmer_entrypoint_test",
    timeout = "short",
    srcs = ["simmer_entrypoint_test.py"],
    args = ["$(location //bin:simmer)"],
    data = ["//bin:simmer"],
)

buildifier(
    name = "buildifier_fix",
    lint_mode = "fix",
    mode = "fix",
)
