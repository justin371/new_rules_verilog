# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_binary")
load("//verilog:defs.bzl", "verilog_rtl_library", "verilog_test")

config_setting(
    name = "target_fastbuild",
    values = {"compilation_mode": "fastbuild"},
)

py_binary(
    name = "verilog_test_tool",
    srcs = ["verilog_test_tool.py"],
    data = ["verilog_test_tool.data"] + select({
        ":target_fastbuild": ["target_config.data"],
        "//conditions:default": ["exec_config.data"],
    }),
)

verilog_rtl_library(
    name = "verilog_test_library",
    direct = ["verilog_test_top.sv"],
)

verilog_test(
    name = "verilog_test_runner_test",
    timeout = "short",
    post_flist_args = ["--post-flist"],
    pre_flist_args = ["--pre-flist"],
    tool = ":verilog_test_tool",
    visibility = ["//tests/starlark_api_validation:__pkg__"],
    deps = [":verilog_test_library"],
)
