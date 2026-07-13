load("@rules_cc//cc:defs.bzl", "cc_binary", "cc_library", "cc_test")

# vim: set ft=bzl :
load("@rules_verilog//verilog:defs.bzl", "verilog_dv_library", "verilog_dv_unit_test", "verilog_rtl_library")

cc_library(
    name = "dpi_c_lib",
    srcs = ["dpi.c"],
    hdrs = ["dpi.h"],
)

cc_binary(
    name = "dpi_c",
    linkshared = True,
    deps = [":dpi_c_lib"],
)

cc_test(
    name = "dpi_c_test",
    srcs = ["dpi_test.c"],
    deps = [":dpi_c_lib"],
)

verilog_dv_library(
    name = "pkg",
    srcs = glob(
        ["*.sv"],
        exclude = ["unit_test_top.sv"],
    ),
    dpi = [":dpi_c"],
    in_flist = ["dpi_pkg.sv"],
)

verilog_rtl_library(
    name = "unit_test_top",
    direct = ["unit_test_top.sv"],
    deps = [":pkg"],
)

verilog_dv_unit_test(
    name = "test",
    tags = [
        "lic_xcelium",
        "requires_license",
    ],
    deps = [":unit_test_top"],
)
