# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_test")
load(
    "@rules_verilog//verilog:defs.bzl",
    "verilog_dv_tb",
    "verilog_dv_unit_test",
    "verilog_rtl_library",
    "verilog_rtl_lint_test",
    "verilog_rtl_unit_test",
)

package(default_visibility = ["//visibility:public"])

verilog_rtl_library(
    name = "unit_test_top",
    modules = ["unit_test_top.sv"],
)

verilog_rtl_lint_test(
    name = "rtl_lint_vcs",
    deps = [":unit_test_top"],
    simulator = "VCS",
    tags = ["manual"],
    top = "unit_test_top",
)

verilog_dv_tb(
    name = "dv_tb_vcs",
    deps = [":unit_test_top"],
    extra_compile_args = [
        "+define+UNIFIED_VCS_COMPILE_ARG",
    ],
    extra_runtime_args = [
        "+UNIFIED_VCS_RUNTIME_ARG",
    ],
    simulator = "VCS",
)

verilog_dv_unit_test(
    name = "dv_unit_vcs",
    deps = [":unit_test_top"],
    simulator = "VCS",
    tags = ["manual"],
)

verilog_dv_unit_test(
    name = "dv_unit_xrun",
    deps = [":unit_test_top"],
    simulator = "XRUN",
    tags = ["manual"],
)

verilog_rtl_unit_test(
    name = "rtl_unit_vcs",
    deps = [":unit_test_top"],
    simulator = "VCS",
    tags = ["manual"],
)

verilog_rtl_unit_test(
    name = "rtl_unit_xrun",
    deps = [":unit_test_top"],
    simulator = "XRUN",
    tags = ["manual"],
)

py_test(
    name = "vcs_filelist_validation_test",
    main = "validate_vcs_filelist_test.py",
    srcs = ["validate_vcs_filelist_test.py"],
    data = [
        ":dv_unit_vcs",
        ":dv_unit_xrun",
        ":dv_tb_vcs",
        ":dv_tb_vcs_compile_args.f",
        ":dv_tb_vcs_runtime_args.f",
        ":rtl_lint_vcs",
        ":rtl_lint_vcs_cmds.tcl",
        ":rtl_unit_vcs",
        ":rtl_unit_xrun",
    ],
)

py_test(
    name = "vcs_runtime_contract_test",
    main = "validate_vcs_runtime_contract_test.py",
    srcs = ["validate_vcs_runtime_contract_test.py"],
    data = [
        "//bin:simmer.py",
        "//bin:templates/rerun_template.sh.j2",
        "//bin:templates/run_waves_template.sh.j2",
        "//bin:templates/sim_template.sh.j2",
        "//bin:templates/vcs_compile_template.sh.j2",
        "//bin:templates/vcs_cov_merge_template.sh.j2",
        "//vendors/synopsys:verilog_dv_tb_compile_args.f.template",
        "//verilog/private:dv.bzl",
        "//verilog/private:rtl.bzl",
    ],
    deps = [
        "//bin:args_parser_lib",
        "//lib/simulators:vcs",
        "//lib/simulators:xcelium",
    ],
)
