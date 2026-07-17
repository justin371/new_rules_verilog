# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_test")
load("@rules_verilog//verilog:defs.bzl", "verilog_rtl_library")

verilog_rtl_library(
    name = "rules_verilog_setup_library",
    direct = ["rules_verilog_external_setup_top.sv"],
)

py_test(
    name = "external_setup_smoke_test",
    srcs = ["rules_verilog_external_setup_smoke_test.py"],
    data = [":rules_verilog_setup_library"],
    main = "rules_verilog_external_setup_smoke_test.py",
    tags = ["manual"],
)
