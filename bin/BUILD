# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@pip_deps//:requirements.bzl", "requirement")

package(default_visibility = ["//visibility:public"])

filegroup(
    name = "regression_report_templates",
    srcs = glob(["templates/regression_report_templates/*.html.j2"]),
)

exports_files([
    "lint_parser_vcs.py",
    "simmer.py",
    "templates/vcs_compile_template.sh.j2",
])

py_binary(
    name = "lint_parser_hal",
    srcs = ["lint_parser_hal.py"],
    deps = [
        "//lib:cmn_logging",
        "//lib:compile_cache",
        requirement("beautifulsoup4"),
    ],
)

py_binary(
    name = "lint_parser_ascent",
    srcs = ["lint_parser_ascent.py"],
    deps = ["//lib:cmn_logging"],
)

py_binary(
    name = "lint_parser_vcs",
    srcs = ["lint_parser_vcs.py"],
    deps = ["//lib:cmn_logging"],
)

py_binary(
    name = "simmer",
    data = glob(["templates/**"]),
    srcs = ["simmer.py"],
    deps = [
        "//bin:check_test",
        "//bin:args_parser",
        "//lib:cmn_logging",
        "//lib:job_lib",
        "//lib:parser_actions",
        "//lib:regression",
        "//lib:rv_utils",
        "//lib:runtime_options",
        "//lib:sim_artifacts",
        "//lib:simmer_results",
        "//lib/simulators:simulators",
        "//lib:regression_report",
        requirement("jinja2"),
    ],
)

py_library(
    name = "args_parser_lib",
    srcs = [
        "args_parser.py",
        "args_parse/__init__.py",
        "args_parse/common.py",
        "args_parse/parser.py",
        "args_parse/vcs.py",
        "args_parse/xcelium.py",
    ],
    deps = ["//lib:parser_actions"],
)

py_binary(
    name = "args_parser",
    srcs = [
        "args_parser.py",
        "args_parse/__init__.py",
        "args_parse/common.py",
        "args_parse/parser.py",
        "args_parse/vcs.py",
        "args_parse/xcelium.py",
    ],
    deps = ["//lib:parser_actions"],
)

py_binary(
    name = "check_test",
    srcs = ["check_test.py"],
)

py_library(
    name = "check_test_lib",
    srcs = ["check_test.py"],
)

py_binary(
    name = "normalize_runfiles_flist",
    srcs = ["normalize_runfiles_flist.py"],
)

py_library(
    name = "normalize_runfiles_flist_lib",
    srcs = ["normalize_runfiles_flist.py"],
)
