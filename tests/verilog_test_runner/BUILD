# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_binary")
load("//verilog:defs.bzl", "verilog_rtl_library", "verilog_test")

py_binary(
    name = "verilog_test_tool",
    srcs = ["verilog_test_tool.py"],
    data = ["verilog_test_tool.data"],
)

verilog_rtl_library(
    name = "verilog_test_library",
    direct = ["verilog_test_top.sv"],
)

verilog_test(
    name = "verilog_test_runner_test",
    post_flist_args = ["--post-flist"],
    pre_flist_args = ["--pre-flist"],
    tool = ":verilog_test_tool",
    deps = [":verilog_test_library"],
)
