# vim: set ft=bzl :
"""Public entry point to all supported Verilog rules and APIs"""

load(
    "//verilog/private:verilog.bzl",
    _verilog_test = "verilog_test",
    _verilog_tool_encapsulation = "verilog_tool_encapsulation",
)
load(
    "//verilog/private:rtl.bzl",
    _verilog_rtl_cdc_test = "verilog_rtl_cdc_test",
    _verilog_rtl_library = "verilog_rtl_library",
    _verilog_rtl_lint_test = "verilog_rtl_lint_test",
    _verilog_rtl_pkg = "verilog_rtl_pkg",
    _verilog_rtl_shell = "verilog_rtl_shell",
    _verilog_rtl_unit_test = "verilog_rtl_unit_test",
)
load(
    "//verilog/private:dv.bzl",
    _verilog_dv_library = "verilog_dv_library",
    _verilog_dv_tb = "verilog_dv_tb",
    _verilog_dv_test_cfg = "verilog_dv_test_cfg",
    _verilog_dv_unit_test = "verilog_dv_unit_test",
)

verilog_tool_encapsulation = _verilog_tool_encapsulation
verilog_test = _verilog_test

verilog_rtl_cdc_test = _verilog_rtl_cdc_test
verilog_rtl_library = _verilog_rtl_library
verilog_rtl_lint_test = _verilog_rtl_lint_test
verilog_rtl_pkg = _verilog_rtl_pkg
verilog_rtl_shell = _verilog_rtl_shell
verilog_rtl_unit_test = _verilog_rtl_unit_test

verilog_dv_library = _verilog_dv_library
verilog_dv_tb = _verilog_dv_tb
verilog_dv_test_cfg = _verilog_dv_test_cfg
verilog_dv_unit_test = _verilog_dv_unit_test
