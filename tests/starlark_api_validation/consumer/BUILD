# vim: set ft=bzl :
load("//verilog:defs.bzl", "verilog_rtl_library", "verilog_test")

verilog_rtl_library(
    name = "consumer_top",
    direct = ["consumer_top.sv"],
)

verilog_test(
    name = "shell_visibility_test",
    timeout = "short",
    pre_flist_args = ["true"],
    shells = ["//tests/starlark_api_validation/shell:visible_shell"],
    deps = [":consumer_top"],
)
