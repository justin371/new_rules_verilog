# vim: set ft=bzl :
load("//verilog:defs.bzl", "verilog_rtl_shell")

verilog_rtl_shell(
    name = "visible_shell",
    module_to_shell_name = "visible",
    shell_module_label = "visible_shell.sv",
    visibility = ["//tests/starlark_api_validation/consumer:__pkg__"],
)
