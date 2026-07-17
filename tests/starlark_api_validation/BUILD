# vim: set ft=bzl :
load("//verilog:defs.bzl", "verilog_dv_library", "verilog_dv_tb", "verilog_dv_test_cfg", "verilog_rtl_library")
load(":fixtures.bzl", "concrete_requires_tb_test", "dpi_runfiles_test", "fake_dpi", "gumi_override_test", "runtime_tool_target_config_test", "target_analyzes_test")

fake_dpi(
    name = "fake_dpi",
    runtime_data = "dpi_runtime.data",
)

verilog_dv_library(
    name = "dpi_library",
    srcs = ["dpi_pkg.sv"],
    dpi = [":fake_dpi"],
)

verilog_rtl_library(
    name = "gumi_override_library",
    direct = ["gumi_top.sv"],
    gumi_file_override = "custom_gumi.vh",
)

verilog_rtl_library(
    name = "tb_sources",
    direct = ["tb_top.sv"],
)

verilog_dv_tb(
    name = "tb",
    simulator = "VCS",
    deps = [":tb_sources"],
)

verilog_dv_test_cfg(
    name = "abstract_cfg",
    abstract = True,
    sim_opts = {"+ABSTRACT_OPTION": ""},
)

verilog_dv_test_cfg(
    name = "concrete_cfg",
    inherits = [":abstract_cfg"],
    tb = ":tb",
)

verilog_dv_test_cfg(
    name = "concrete_without_tb",
    inherits = [":abstract_cfg"],
    tags = ["manual"],
)

concrete_requires_tb_test(
    name = "concrete_requires_tb_test",
    target_under_test = ":concrete_without_tb",
)

gumi_override_test(
    name = "gumi_override_test",
    target_under_test = ":gumi_override_library",
)

dpi_runfiles_test(
    name = "dpi_runfiles_test",
    target_under_test = ":dpi_library",
)

runtime_tool_target_config_test(
    name = "runtime_tool_target_config_test",
    target_under_test = "//tests/verilog_test_runner:verilog_test_runner_test",
)

target_analyzes_test(
    name = "abstract_cfg_test",
    target_under_test = ":abstract_cfg",
)

target_analyzes_test(
    name = "concrete_cfg_test",
    target_under_test = ":concrete_cfg",
)
