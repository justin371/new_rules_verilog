load("@rules_python//python:defs.bzl", "py_binary")
load("@rules_verilog//verilog:defs.bzl", "verilog_rtl_library")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "verilog_test_tool",
    srcs = ["verilog_test_tool.py"],
    main = "verilog_test_tool.py",
)

verilog_rtl_library(
    name = "verilog_test_library",
    direct = ["external_top.sv"],
)
