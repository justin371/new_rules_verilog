"""VCS backend helpers for DV rules."""

load("//verilog/private:verilog.bzl", "ToolEncapsulationInfo", "VerilogInfo", "flists_to_arguments")

def _sanitize_defines(defines):
    sanitized = {}
    for key, value in defines.items():
        if key in ["CADENCE", "XRUN"]:
            continue
        sanitized[key] = value
    return sanitized

def _sanitize_compile_args(compile_args):
    sanitized = []
    for arg in compile_args:
        if arg.startswith("+define+CADENCE") or arg.startswith("+define+XRUN"):
            continue
        if arg.startswith("-define CADENCE") or arg.startswith("-define XRUN"):
            continue
        sanitized.append(arg)
    return sanitized

def _validate_tb(ctx, has_msie_primary, has_msie_extras):
    if ctx.files.ccf:
        fail("verilog_dv_tb {} ccf is Xcelium-only; use VCS -cm options instead".format(ctx.label))
    if ctx.file.xcelium_covfile:
        fail("verilog_dv_tb {} xcelium_covfile cannot be used with VCS".format(ctx.label))
    if has_msie_primary or has_msie_extras:
        fail("verilog_dv_tb {} MSIE attributes are Xcelium-only".format(ctx.label))

def _config_arg(cfg):
    return cfg

def _compile_config(ctx, defines, compile_args):
    return struct(
        args = _sanitize_compile_args(compile_args),
        defines = "\n".join(["+define+{}{}".format(key, value) for key, value in _sanitize_defines(defines).items()]),
        flists = flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", "\n-file"),
        template = ctx.file._compile_args_template_vcs,
    )

def _extra_compile_outputs(ctx, defines, selected_compile_args, compile_config):
    return struct(
        generated_outputs = [],
        incremental_compile_args = None,
        primary_compile_args = None,
        primary_inputs = None,
    )

def _runtime_config(ctx):
    return struct(
        dpi = flists_to_arguments(
            ctx.attr.shells + ctx.attr.deps,
            VerilogInfo,
            "transitive_dpi",
            "-sv_lib",
            "\n",
            "vcs",
            "bazel_runfiles_main/",
        ),
        template = ctx.file._default_sim_opts_vcs,
    )

def _unit_test_config(ctx, unit_test_template, default_sim_opts, simulator_command, filelist_flag, dpi_tool):
    if unit_test_template.short_path == ctx.file._ut_sim_template_xrun_default.short_path:
        unit_test_template = ctx.file._ut_sim_template_vcs_default
    if default_sim_opts.short_path == ctx.file._default_sim_opts_xrun_default.short_path:
        default_sim_opts = ctx.file._default_sim_opts_vcs_default
    return struct(
        default_sim_opts = default_sim_opts,
        dpi_tool = "vcs",
        filelist_flag = "-file",
        simulator_command = ctx.attr._command_override_vcs[ToolEncapsulationInfo].command,
        unit_test_template = unit_test_template,
    )

vcs_dv_backend = struct(
    compile_config = _compile_config,
    config_arg = _config_arg,
    extra_compile_outputs = _extra_compile_outputs,
    runtime_config = _runtime_config,
    unit_test_config = _unit_test_config,
    validate_tb = _validate_tb,
)
