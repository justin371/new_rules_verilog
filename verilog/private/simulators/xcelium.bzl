"""Xcelium backend helpers for DV rules."""

load("//verilog/private:verilog.bzl", "VerilogInfo", "flists_to_arguments", "get_transitive_srcs", "runfiles_relative_short_path")

def _validate_tb(ctx, has_msie_primary, has_msie_extras):
    if ctx.file.vcs_cm_hier:
        fail("verilog_dv_tb {} vcs_cm_hier cannot be used with Xcelium".format(ctx.label))
    if not has_msie_primary and has_msie_extras:
        fail("verilog_dv_tb {} MSIE extra compile arguments require MSIE dependencies".format(ctx.label))

def _config_arg(cfg):
    return "-compcnfg {}".format(cfg)

def _compile_config(ctx, defines, compile_args):
    return struct(
        args = compile_args,
        defines = "\n".join(["-define {}{}".format(key, value) for key, value in defines.items()]),
        flists = flists_to_arguments(ctx.attr.deps + ctx.attr.shells, VerilogInfo, "transitive_flists", "\n-f"),
        template = ctx.file._compile_args_template_xrun,
    )

def _msie_input_inventory(deps, extra_files):
    entries = []
    sources = get_transitive_srcs([], deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    flists = get_transitive_srcs([], deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    for source in sources.to_list():
        entries.append("source\t{}".format(runfiles_relative_short_path(source)))
    for flist in flists.to_list():
        entries.append("filelist\t{}".format(runfiles_relative_short_path(flist)))
    for extra_file in extra_files:
        entries.append("runfile\t{}".format(runfiles_relative_short_path(extra_file)))
    return "\n".join(sorted(depset(entries).to_list())) + "\n"

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
        content = _msie_input_inventory(
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

def _unit_test_config(ctx, unit_test_template, default_sim_opts, simulator_command, filelist_flag, dpi_tool):
    return struct(
        default_sim_opts = default_sim_opts,
        dpi_tool = dpi_tool,
        filelist_flag = filelist_flag,
        simulator_command = simulator_command,
        unit_test_template = unit_test_template,
    )

xcelium_dv_backend = struct(
    compile_config = _compile_config,
    config_arg = _config_arg,
    extra_compile_outputs = _extra_compile_outputs,
    runtime_config = _runtime_config,
    unit_test_config = _unit_test_config,
    validate_tb = _validate_tb,
)
