# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_library")
load("@pip_deps//:requirements.bzl", "requirement")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "cmn_logging",
    srcs = ["cmn_logging.py"],
)

py_library(
    name = "job_lib",
    srcs = ["job_lib.py"],
    deps = [":runtime_options"],
)

py_library(
    name = "parser_actions",
    srcs = ["parser_actions.py"],
)

py_library(
    name = "regression",
    srcs = ["regression.py"],
    deps = ["rv_utils"],
)

py_library(
    name = "rv_utils",
    srcs = ["rv_utils.py"],
    deps = [requirement("beautifulsoup4")],
)

py_library(
    name = "regression_report",
    srcs = ["regression_report.py"],
)

py_library(
    name = "runtime_options",
    srcs = ["runtime_options.py"],
)

py_library(
    name = "sim_artifacts",
    srcs = ["sim_artifacts.py"],
)

py_library(
    name = "simmer_results",
    srcs = ["simmer_results.py"],
)
