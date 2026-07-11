# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_test")
load(
    "@rules_verilog//verilog:defs.bzl",
    "verilog_dv_tb",
    "verilog_dv_test_cfg",
    "verilog_dv_unit_test",
    "verilog_rtl_library",
    "verilog_rtl_lint_test",
    "verilog_rtl_unit_test",
)

package(default_visibility = ["//visibility:public"])

filegroup(
    name = "vcs_partitions",
    srcs = ["vcs_partitions.cfg"],
)

verilog_rtl_library(
    name = "unit_test_top",
    modules = ["unit_test_top.sv"],
    deps = ["@filelist_external_fixture//:external_rtl"],
)

verilog_rtl_lint_test(
    name = "rtl_lint_vcs",
    simulator = "VCS",
    tags = ["manual"],
    top = "unit_test_top",
    deps = [":unit_test_top"],
)

verilog_dv_tb(
    name = "dv_tb_vcs",
    extra_compile_args = [
        "+define+UNIFIED_VCS_COMPILE_ARG",
        "+optconfigfile+$(location :vcs_partitions)",
    ],
    extra_runfiles = [":vcs_partitions"],
    extra_runtime_args = [
        "+UNIFIED_VCS_RUNTIME_ARG",
    ],
    run_fail_patterns = ["^PROJECT FAIL$"],
    run_pass_patterns = ["^PROJECT PASS$"],
    simulator = "VCS",
    vcs_cm_hier = "coverage_hier.cfg",
    deps = [":unit_test_top"],
)

verilog_dv_tb(
    name = "dv_tb_xrun_ccf",
    ccf = ["coverage.ccf"],
    msie_incremental_deps = ["@filelist_external_fixture//:external_rtl"],
    msie_incremental_extra_compile_args = ["-define MSIE_INCREMENTAL"],
    msie_primary_deps = [":unit_test_top"],
    msie_primary_extra_compile_args = [
        "-define MSIE_PRIMARY",
        "-covfile $(location :coverage.ccf)",
    ],
    msie_primary_extra_runfiles = [":coverage.ccf"],
    simulator = "XRUN",
    deps = [":unit_test_top"],
)

verilog_dv_test_cfg(
    name = "dv_cfg_vcs",
    timeout = 17,
    simulator = "VCS",
    tags = ["manual"],
    tb = ":dv_tb_vcs",
)

verilog_dv_test_cfg(
    name = "dv_cfg_vcs_inherited",
    inherits = [":dv_cfg_vcs"],
    tags = ["manual"],
)

verilog_dv_test_cfg(
    name = "dv_cfg_vcs_no_timeout",
    timeout = 0,
    tags = ["manual"],
    tb = ":dv_tb_vcs",
)

verilog_dv_unit_test(
    name = "dv_unit_vcs",
    compile_args = ["+UNIT_VCS_COMPILE_ARG"],
    run_args = ["+UNIT_VCS_RUN_ARG"],
    simulator = "VCS",
    tags = ["manual"],
    deps = [":unit_test_top"],
)

verilog_dv_unit_test(
    name = "dv_unit_xrun",
    simulator = "XRUN",
    tags = ["manual"],
    deps = [":unit_test_top"],
)

verilog_rtl_unit_test(
    name = "rtl_unit_vcs",
    simulator = "VCS",
    tags = ["manual"],
    deps = [":unit_test_top"],
)

verilog_rtl_unit_test(
    name = "rtl_unit_xrun",
    simulator = "XRUN",
    tags = ["manual"],
    deps = [":unit_test_top"],
)

py_test(
    name = "vcs_filelist_validation_test",
    srcs = ["validate_vcs_filelist_test.py"],
    data = [
        ":dv_cfg_vcs",
        ":dv_cfg_vcs_inherited",
        ":dv_cfg_vcs_no_timeout",
        ":dv_tb_vcs",
        ":dv_tb_vcs_compile_args.f",
        ":dv_tb_vcs_runtime_args.f",
        ":dv_tb_vcs_tb_options.py",
        ":dv_tb_xrun_ccf",
        ":dv_tb_xrun_ccf_compile_args.f",
        ":dv_tb_xrun_ccf_tb_options.py",
        ":dv_unit_vcs",
        ":dv_unit_xrun",
        ":rtl_lint_vcs",
        ":rtl_lint_vcs_cmds.tcl",
        ":rtl_unit_vcs",
        ":rtl_unit_xrun",
        ":vcs_partitions",
        "@filelist_external_fixture//:external_rtl",
    ],
    main = "validate_vcs_filelist_test.py",
)

py_test(
    name = "vcs_runtime_contract_test",
    srcs = ["validate_vcs_runtime_contract_test.py"],
    data = [
        "//bin:simmer.py",
        "//bin:templates/rerun_template.sh.j2",
        "//bin:templates/run_waves_template.sh.j2",
        "//bin:templates/sim_template.sh.j2",
        "//bin:templates/vcs_compile_template.sh.j2",
        "//bin:templates/vcs_cov_merge_template.sh.j2",
        "//bin:templates/xrun_compile_template.sh.j2",
        "//bin:templates/xrun_wave_cmd_template.tcl.j2",
        "//vendors/cadence:verilog_rtl_cdc_test.sh.template",
        "//vendors/cadence:verilog_rtl_lint_test.sh.template",
        "//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template",
        "//vendors/real_intent:verilog_rtl_lint_test.sh.template",
        "//vendors/synopsys:verilog_dv_tb_compile_args.f.template",
        "//vendors/synopsys:verilog_rtl_lint_test.sh.template",
        "//verilog/private:dv.bzl",
        "//verilog/private:rtl.bzl",
        "//verilog/private:simulators/pldm.bzl",
        "//verilog/private:simulators/vcs.bzl",
        "//verilog/private:simulators/xcelium.bzl",
    ],
    main = "validate_vcs_runtime_contract_test.py",
    deps = [
        "//bin:args_parser_lib",
        "//bin:lint_parser_hal",
        "//lib:job_lib",
        "//lib:runtime_options",
        "//lib/simulators:vcs",
        "//lib/simulators:xcelium",
    ],
)
