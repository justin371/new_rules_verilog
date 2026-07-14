"""VCS backend helpers for DV rules."""

load("//verilog/private:verilog.bzl", "VerilogInfo", "flists_to_arguments", "runfiles_relative_short_path")

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
        if arg in ["+define+CADENCE", "+define+XRUN", "-define CADENCE", "-define XRUN"]:
            continue
        if any([arg.startswith(prefix) for prefix in [
            "+define+CADENCE=",
            "+define+XRUN=",
            "-define CADENCE=",
            "-define XRUN=",
        ]]):
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
        fallback_flist_field = "transitive_flists",
        flist_field = "transitive_vcs_flists",
        flists = flists_to_arguments(
            ctx.attr.shells + ctx.attr.deps,
            VerilogInfo,
            "transitive_vcs_flists",
            "\n-file",
            fallback_field = "transitive_flists",
        ),
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

def _tb_options(ctx, unused_extra_compile_outputs, unused_xcelium_covfile):
    return {
        "vcs_cm_hier": runfiles_relative_short_path(ctx.file.vcs_cm_hier) if ctx.file.vcs_cm_hier else "",
    }

vcs_dv_backend = struct(
    compile_config = _compile_config,
    config_arg = _config_arg,
    extra_compile_outputs = _extra_compile_outputs,
    runtime_config = _runtime_config,
    tb_options = _tb_options,
    validate_tb = _validate_tb,
)
