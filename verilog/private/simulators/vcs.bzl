"""VCS backend helpers for DV rules."""

load("//verilog/private:verilog.bzl", "ToolEncapsulationInfo", "VerilogInfo", "flists_to_arguments", "get_transitive_srcs", "merge_default_runfiles", "normalize_vcs_unit_test_compile_args", "runfiles_relative_short_path")

def _use_vcs_default(selected_file, xrun_default_file, vcs_default_file):
    if selected_file.short_path == xrun_default_file.short_path:
        return vcs_default_file
    return selected_file

def vcs_dv_unit_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_sources")
    flists = get_transitive_srcs(
        [],
        ctx.attr.deps,
        VerilogInfo,
        "transitive_vcs_flists",
        fallback_attr_name = "transitive_flists",
    )
    dpi = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_dpi")
    flists_list = flists.to_list()
    default_sim_opts = _use_vcs_default(
        ctx.file.default_sim_opts,
        ctx.file._default_sim_opts_xrun,
        ctx.file._default_sim_opts_vcs,
    )
    unit_test_template = _use_vcs_default(
        ctx.file.ut_sim_template,
        ctx.file._ut_sim_template_xrun,
        ctx.file._ut_sim_template_vcs,
    )
    sim_arg_values = normalize_vcs_unit_test_compile_args(ctx.attr.sim_args)
    compile_arg_values = sim_arg_values + normalize_vcs_unit_test_compile_args(ctx.attr.compile_args)

    compile_args = ctx.actions.declare_file(ctx.label.name + "_compile_args.f")
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_vcs,
        output = compile_args,
        substitutions = {
            "{COMPILE_ARGS}": "\n".join(compile_arg_values),
            "{DEFINES}": "",
            "{FLISTS}": "\n".join(["-file {}".format(runfiles_relative_short_path(f)) for f in flists_list]),
        },
    )

    runtime_args = ctx.actions.declare_file(ctx.label.name + "_runtime_args.f")
    ctx.actions.expand_template(
        template = default_sim_opts,
        output = runtime_args,
        substitutions = {
            "{DPI_LIBS}": "",
            "{RUNTIME_ARGS}": "",
        },
    )

    simulator_command = ctx.attr._command_override_vcs[ToolEncapsulationInfo].command
    flist_args = " ".join(["-file {}".format(runfiles_relative_short_path(f)) for f in flists_list])
    ctx.actions.expand_template(
        template = unit_test_template,
        output = ctx.outputs.out,
        substitutions = {
            "{COMPILE_ARGS}": " ".join(compile_arg_values),
            "{SIMULATOR_COMMAND}": simulator_command,
            "{SIMULATOR_RUNNER}": ctx.attr._vcs_unit_test_runner[ToolEncapsulationInfo].command,
            "{COMPILE_ARGS_FILE}": runfiles_relative_short_path(compile_args),
            "{DEFAULT_SIM_OPTS}": "-f {}".format(runfiles_relative_short_path(runtime_args)),
            "{DPI_LIBS}": flists_to_arguments(ctx.attr.deps, VerilogInfo, "transitive_dpi", "-sv_lib", "", "vcs"),
            "{FLISTS}": flist_args,
            "{RUN_ARGS}": " ".join(ctx.attr.run_args),
            "{SIM_ARGS}": " ".join(sim_arg_values),
        },
        is_executable = True,
    )

    runfiles = merge_default_runfiles(
        ctx,
        files = flists_list + trans_srcs.to_list() + dpi.to_list() + [compile_args, runtime_args],
        targets = ctx.attr.deps + [ctx.attr.default_sim_opts],
    )
    return [DefaultInfo(
        runfiles = runfiles,
        executable = ctx.outputs.out,
    )]

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
    if ctx.attr.vcs_three_step and ctx.attr.extra_compile_args:
        fail(
            (
                "verilog_dv_tb {} vcs_three_step requires analysis and elaboration options to be split between " +
                "vcs_vlogan_args and vcs_elab_args; extra_compile_args must be empty"
            ).format(ctx.label),
        )
    if ctx.attr.vcs_three_step and ctx.attr.verilog_config:
        fail(
            (
                "verilog_dv_tb {} vcs_three_step does not yet support verilog_config; analyze the configuration " +
                "source through vcs_vlogan_args and select its top through vcs_elab_args"
            ).format(ctx.label),
        )
    if not ctx.attr.vcs_three_step and (ctx.attr.vcs_vlogan_args or ctx.attr.vcs_elab_args):
        fail(
            "verilog_dv_tb {} vcs_vlogan_args and vcs_elab_args require vcs_three_step = True".format(ctx.label),
        )

def _materialize_library_flist(ctx, source_lines, default_flist):
    if not ctx.attr.makelib:
        return default_flist
    output = ctx.actions.declare_file(ctx.label.name + "_vcs.f")
    ctx.actions.write(
        output = output,
        content = "\n".join(source_lines),
    )
    return output

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
    if ctx.attr.vcs_three_step:
        vlogan_args_file = ctx.actions.declare_file(ctx.label.name + "_vlogan_args.f")
        vlogan_filelists = ctx.actions.declare_file(ctx.label.name + "_vlogan_filelists.txt")
        elab_args_file = ctx.actions.declare_file(ctx.label.name + "_elab_args.f")
        flists = get_transitive_srcs(
            [],
            ctx.attr.shells + ctx.attr.deps,
            VerilogInfo,
            "transitive_vcs_flists",
            fallback_attr_name = "transitive_flists",
        ).to_list()
        ctx.actions.expand_template(
            template = ctx.file._vlogan_args_template_vcs,
            output = vlogan_args_file,
            substitutions = {
                "{DEFINES}": "\n".join(["+define+{}{}".format(key, value) for key, value in _sanitize_defines(defines).items()]),
                "{VLOGAN_ARGS}": ctx.expand_location(
                    "\n".join(ctx.attr.vcs_vlogan_args),
                    targets = ctx.attr.extra_runfiles,
                ),
            },
        )
        ctx.actions.write(
            output = vlogan_filelists,
            content = "\n".join([runfiles_relative_short_path(flist) for flist in flists]) + "\n",
        )
        ctx.actions.expand_template(
            template = ctx.file._elab_args_template_vcs,
            output = elab_args_file,
            substitutions = {
                "{ELAB_ARGS}": ctx.expand_location(
                    "\n".join(ctx.attr.vcs_elab_args),
                    targets = ctx.attr.extra_runfiles,
                ),
            },
        )
        return struct(
            generated_outputs = [
                vlogan_args_file,
                vlogan_filelists,
                elab_args_file,
            ],
            incremental_compile_args = None,
            primary_compile_args = None,
            primary_inputs = None,
            vcs_elab_args = elab_args_file,
            vcs_vlogan_args = vlogan_args_file,
            vcs_vlogan_filelists = vlogan_filelists,
        )

    return struct(
        generated_outputs = [],
        incremental_compile_args = None,
        primary_compile_args = None,
        primary_inputs = None,
        vcs_elab_args = None,
        vcs_vlogan_args = None,
        vcs_vlogan_filelists = None,
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

def _tb_options(ctx, extra_compile_outputs, unused_xcelium_covfile):
    options = {
        "vcs_cm_hier": runfiles_relative_short_path(ctx.file.vcs_cm_hier) if ctx.file.vcs_cm_hier else "",
        "vcs_three_step": ctx.attr.vcs_three_step,
    }
    if ctx.attr.vcs_three_step:
        options.update({
            "vcs_elab_args": runfiles_relative_short_path(extra_compile_outputs.vcs_elab_args),
            "vcs_vlogan_args": runfiles_relative_short_path(extra_compile_outputs.vcs_vlogan_args),
            "vcs_vlogan_filelists": runfiles_relative_short_path(extra_compile_outputs.vcs_vlogan_filelists),
        })
    return options

vcs_dv_backend = struct(
    compile_config = _compile_config,
    config_arg = _config_arg,
    extra_compile_outputs = _extra_compile_outputs,
    materialize_library_flist = _materialize_library_flist,
    runtime_config = _runtime_config,
    tb_options = _tb_options,
    validate_tb = _validate_tb,
)
