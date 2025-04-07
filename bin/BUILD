load("@rules_python//python:defs.bzl", "py_binary")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "lint_parser_hal",
    srcs = ["lint_parser_hal.py"],
    deps = ["//lib:cmn_logging"],
)

py_binary(
    name = "lint_parser_ascent",
    srcs = ["lint_parser_ascent.py"],
    deps = ["//lib:cmn_logging"],
)

py_binary(
    name = "simmer",
    srcs = ["simmer.py"],
    deps = [
        "//bin:check_test",
        "//bin:args_parser",
        "//lib:cmn_logging",
        "//lib:job_lib",
        "//lib:parser_actions",
        "//lib:regression",
        "//lib:rv_utils",
        "//lib/simulators:simulators",
    ],
)

py_binary(
    name = "args_parser",
    srcs = ["args_parser.py"],
    deps = ["//lib:parser_actions"],
)

py_binary(
    name = "check_test",
    srcs = ["check_test.py"],
    deps = ["//lib:cmn_logging"],
)
