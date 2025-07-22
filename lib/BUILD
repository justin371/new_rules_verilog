load("@rules_python//python:defs.bzl", "py_library")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "cmn_logging",
    srcs = ["cmn_logging.py"],
)

py_library(
    name = "job_lib",
    srcs = ["job_lib.py"],
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
)

py_library(
    name = "regression_report",
    srcs = ["regression_report.py"],
)
