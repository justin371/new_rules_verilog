# vim: set ft=bzl :
load("@rules_verilog//verilog:defs.bzl", "verilog_rtl_library", "verilog_rtl_pkg", "verilog_rtl_unit_test")

verilog_rtl_pkg(
    name = "apb_pkg",
    direct = ["apb_pkg.sv"],
)

verilog_rtl_library(
    name = "apb",
    modules = [
        "apb.sv",
    ],
    deps = [
        ":apb_pkg",
    ],
)

verilog_rtl_library(
    name = "unit_test_top",
    modules = ["unit_test_top.sv"],
    deps = [":apb"],
)

verilog_rtl_unit_test(
    name = "test",
    tags = [
        "lic_xcelium",
        "requires_license",
    ],
    deps = [":unit_test_top"],
)
