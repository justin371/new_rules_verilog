# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_library")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "bazel_profile",
    srcs = ["bazel_profile.py"],
)

py_library(
    name = "cmn_logging",
    srcs = ["cmn_logging.py"],
)

py_library(
    name = "compile_cache",
    srcs = ["compile_cache.py"],
)

py_library(
    name = "coverage_data",
    srcs = ["coverage_data.py"],
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
    deps = [
        ":bazel_profile",
        ":rv_utils",
    ],
)

py_library(
    name = "rv_utils",
    srcs = ["rv_utils.py"],
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
    name = "seed_plan",
    srcs = ["seed_plan.py"],
)

py_library(
    name = "sim_artifacts",
    srcs = ["sim_artifacts.py"],
)

py_library(
    name = "simmer_results",
    srcs = ["simmer_results.py"],
)
