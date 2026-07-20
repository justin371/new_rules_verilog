"""Xcelium backend helpers for DV rules."""

load("//verilog/private:verilog.bzl", "ToolEncapsulationInfo", "VerilogInfo", "flists_to_arguments", "get_transitive_srcs", "merge_default_runfiles", "runfiles_relative_short_path", "verilog_input_inventory")

def _validate_tb(ctx, has_msie_primary, has_msie_extras):
    if ctx.file.vcs_cm_hier:
        fail("verilog_dv_tb {} vcs_cm_hier cannot be used with Xcelium".format(ctx.label))
    if not has_msie_primary and has_msie_extras:
        fail("verilog_dv_tb {} MSIE extra compile arguments require MSIE dependencies".format(ctx.label))

def _config_arg(cfg):
    return "-compcnfg {}".format(cfg)

def _materialize_library_flist(ctx, source_lines):
    content = source_lines
    if ctx.attr.makelib:
        content = ["-makelib", ctx.attr.makelib] + content + ["-endlib"]
    ctx.actions.write(
        output = ctx.outputs.out,
        content = "\n".join(content),
    )
    return ctx.outputs.out

def _compile_config(ctx, defines, compile_args):
    return struct(
        args = compile_args,
        defines = "\n".join(["-define {}{}".format(key, value) for key, value in defines.items()]),
        fallback_flist_field = None,
        flist_field = "transitive_flists",
        flists = flists_to_arguments(ctx.attr.deps + ctx.attr.shells, VerilogInfo, "transitive_flists", "\n-f"),
        template = ctx.file._compile_args_template_xrun,
    )

def _expand_msie_compile_args(ctx, compile_args, compile_defines):
    if len(ctx.attr.msie_primary_deps) == 0:
        return struct(
            incremental_compile_args = None,
            outputs = [],
            primary_compile_args = None,
            primary_inputs = None,
        )

    primary_compile_args = ctx.actions.declare_file(ctx.label.name + "_msie_primary_compile_args.f")
    incremental_compile_args = ctx.actions.declare_file(ctx.label.name + "_msie_incremental_compile_args.f")
    primary_inputs = ctx.actions.declare_file(ctx.label.name + "_msie_primary_inputs.txt")
    common_xrun_args = ctx.expand_location("\n".join(compile_args), targets = ctx.attr.extra_runfiles)
    primary_xrun_args = ctx.expand_location(
        "\n".join(ctx.attr.msie_primary_extra_compile_args),
        targets = ctx.attr.extra_runfiles + ctx.attr.msie_primary_extra_runfiles,
    )
    incremental_xrun_args = ctx.expand_location(
        "\n".join(ctx.attr.msie_incremental_extra_compile_args),
        targets = ctx.attr.extra_runfiles + ctx.attr.msie_incremental_extra_runfiles,
    )
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_xrun,
        output = primary_compile_args,
        substitutions = {
            "{COMPILE_ARGS}": "\n".join([arg for arg in [common_xrun_args, primary_xrun_args] if arg]),
            "{DEFINES}": compile_defines,
            "{FLISTS}": flists_to_arguments(ctx.attr.msie_primary_deps, VerilogInfo, "transitive_flists", "\n-f"),
        },
    )
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_xrun,
        output = incremental_compile_args,
        substitutions = {
            "{COMPILE_ARGS}": "\n".join([arg for arg in [common_xrun_args, incremental_xrun_args] if arg]),
            "{DEFINES}": compile_defines,
            "{FLISTS}": flists_to_arguments(ctx.attr.msie_incremental_deps, VerilogInfo, "transitive_flists", "\n-f"),
        },
    )
    ctx.actions.write(
        output = primary_inputs,
        content = verilog_input_inventory(
            ctx.attr.msie_primary_deps,
            ctx.files.extra_runfiles + ctx.files.msie_primary_extra_runfiles,
        ),
    )
    return struct(
        incremental_compile_args = incremental_compile_args,
        outputs = [primary_compile_args, incremental_compile_args, primary_inputs],
        primary_compile_args = primary_compile_args,
        primary_inputs = primary_inputs,
    )

def _extra_compile_outputs(ctx, defines, selected_compile_args, compile_config):
    msie = _expand_msie_compile_args(ctx, compile_config.args, compile_config.defines)
    return struct(
        generated_outputs = [ctx.outputs.compile_args_pldm_ice, ctx.outputs.compile_args_pldm_sa] + msie.outputs,
        incremental_compile_args = msie.incremental_compile_args,
        primary_compile_args = msie.primary_compile_args,
        primary_inputs = msie.primary_inputs,
    )

def _runtime_config(ctx):
    return struct(
        dpi = flists_to_arguments(
            ctx.attr.shells + ctx.attr.deps,
            VerilogInfo,
            "transitive_dpi",
            "-sv_lib",
            "\n",
            None,
            "bazel_runfiles_main/",
        ),
        template = ctx.file._default_sim_opts_xrun,
    )

def _tb_options(unused_ctx, extra_compile_outputs, xcelium_covfile):
    return {
        "msie_incremental_compile_args": runfiles_relative_short_path(extra_compile_outputs.incremental_compile_args) if extra_compile_outputs.incremental_compile_args else "",
        "msie_primary_compile_args": runfiles_relative_short_path(extra_compile_outputs.primary_compile_args) if extra_compile_outputs.primary_compile_args else "",
        "msie_primary_inputs": runfiles_relative_short_path(extra_compile_outputs.primary_inputs) if extra_compile_outputs.primary_inputs else "",
        "xcelium_covfile": runfiles_relative_short_path(xcelium_covfile) if xcelium_covfile else "",
    }

def xcelium_dv_unit_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_sources")
    flists = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_flists")
    dpi = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_dpi")
    flists_list = flists.to_list()
    default_sim_opts = ctx.file.default_sim_opts
    filelist_flag = "-f"

    ctx.actions.expand_template(
        template = ctx.file.ut_sim_template,
        output = ctx.outputs.out,
        substitutions = {
            "{SIMULATOR_COMMAND}": ctx.attr._command_override[ToolEncapsulationInfo].command,
            "{DEFAULT_SIM_OPTS}": "{} {}".format(filelist_flag, runfiles_relative_short_path(default_sim_opts)),
            "{DPI_LIBS}": flists_to_arguments(ctx.attr.deps, VerilogInfo, "transitive_dpi", "-sv_lib", "", None),
            "{FLISTS}": " ".join(["{} {}".format(filelist_flag, runfiles_relative_short_path(f)) for f in flists_list]),
            "{SIM_ARGS}": " ".join(ctx.attr.sim_args),
            "{COMPILE_ARGS}": " ".join(ctx.attr.sim_args + ctx.attr.compile_args),
            "{RUN_ARGS}": " ".join(ctx.attr.run_args),
        },
        is_executable = True,
    )

    runfiles = merge_default_runfiles(
        ctx,
        files = flists_list + trans_srcs.to_list() + dpi.to_list() + [default_sim_opts],
        targets = ctx.attr.deps + [ctx.attr.default_sim_opts],
    )
    return [DefaultInfo(
        runfiles = runfiles,
        executable = ctx.outputs.out,
    )]

xcelium_dv_backend = struct(
    compile_config = _compile_config,
    config_arg = _config_arg,
    extra_compile_outputs = _extra_compile_outputs,
    materialize_library_flist = _materialize_library_flist,
    runtime_config = _runtime_config,
    tb_options = _tb_options,
    validate_tb = _validate_tb,
)
