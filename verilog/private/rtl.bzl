# vim: set ft=bzl :
"""Rules to gather and compile RTL."""

load(":verilog.bzl", "CUSTOM_SHELL", "ShellInfo", "ToolEncapsulationInfo", "VerilogInfo", "gather_shell_defines", "get_transitive_srcs", "merge_default_runfiles", "partition_vcs_unit_test_args", "resolve_unit_test_simulator", "runfiles_relative_short_path")

_SHELLS_DOC = """List of verilog_rtl_shell Labels.
For each Label, a gumi define will be placed on the command line to use this shell instead of the original module.
This requires that the original module was instantiated using \\`gumi_<module_name> instead of just <module_name>."""

def _resolve_unit_test_default_file(simulator, selected_file, xrun_default_file, vcs_default_file):
    if simulator == "VCS" and selected_file.short_path == xrun_default_file.short_path:
        return vcs_default_file
    return selected_file

def _split_label_package_name(label):
    value = str(label)
    if "//" in value:
        value = value.split("//", 1)[1]
    if ":" in value:
        package, name = value.split(":", 1)
    else:
        package = value
        name = value.rsplit("/", 1)[-1]
    return package, name

def _label_matches_default(selected_label, default_label):
    selected_package, selected_name = _split_label_package_name(selected_label)
    default_package, default_name = _split_label_package_name(default_label)
    return selected_package == default_package and selected_name == default_name

def _resolve_label_default_file(simulator, selected_label, xrun_default_label, xrun_default_file, vcs_default_file):
    if simulator == "VCS" and _label_matches_default(selected_label, xrun_default_label):
        return vcs_default_file
    return xrun_default_file

def create_flist_content(ctx, gumi_path, allow_library_discovery, makelib = "", no_synth = False):
    """Create the content of a '.f' file.

    Args:
      gumi_path: The path to the dynamically created gumi file to include.

        The gumi file is put directly on the command line to ensure that the
        defines are always used.
      allow_library_discovery: When false, modules are placed directly on the command line.

        Preference is to use the -y (modules in this directory can be found by
        searching for a file with the same name) and -v (file is a library file
        containing multiple modules) flags. Some tools, e.g. Genus, do not
        handle -y correctly when invoked many times. As a workaround for these
        tools, setting allow_library_discovery to false will put all module
        files and library files directly onto the command line.
      no_synth: When true, omit synthesizable source entries for downstream
        synthesis aspects. Simulation callers leave this false and retain the
        complete library.
    Returns:
      List of strings representing flist content.
    """
    flist_content = []

    # if using makelib, start here
    if len(makelib) and not no_synth:
        flist_content.append("-makelib")
        flist_content.append(makelib)

    # Using dirname may result in bazel-out included in path
    incdir = depset([runfiles_relative_short_path(f)[:-len(f.basename) - 1] for f in ctx.files.headers]).to_list()
    for d in incdir:
        flist_content.append("+incdir+{}".format(d))

    # Using dirname may result in bazel-out included in path
    libdir = depset([runfiles_relative_short_path(f)[:-len(f.basename) - 1] for f in ctx.files.modules]).to_list()

    flist_content.append(gumi_path)

    if not no_synth:
        if allow_library_discovery:
            for d in libdir:
                if d == "":
                    d = "."
                flist_content.append("-y {}".format(d))
        else:
            flist_content += [runfiles_relative_short_path(f) for f in ctx.files.modules]

        for f in ctx.files.lib_files:
            if allow_library_discovery:
                flist_content.append("-v {}".format(runfiles_relative_short_path(f)))
            else:
                flist_content.append(runfiles_relative_short_path(f))

        for f in ctx.files.direct:
            flist_content.append(runfiles_relative_short_path(f))

    # if using makelib, terminate here
    if len(makelib) and not no_synth:
        flist_content.append("-endlib")

    flist_content.append("")
    return flist_content

def _verilog_rtl_library_impl(ctx):
    srcs = ctx.files.headers + ctx.files.modules + ctx.files.lib_files + ctx.files.direct

    if ctx.attr.is_pkg:
        # FIXME opu_tx_rx is failing this check
        # for dep in ctx.attr.deps:
        #     if ShellInfo in dep and not dep[ShellInfo].is_pkg:
        #         fail("verilog_rtl_pkg may only depend on other verilog_rtl_pkg instances")
        pass
    else:
        for src in srcs:
            if "_pkg" in src.basename:
                fail("Package files should not declared in a verilog_rtl_library. Use a verilog_rtl_pkg instead. {} is declared in {}".format(src, ctx.label))

    if ctx.attr.is_shell_of:
        if len(ctx.attr.modules) != 1 and not ctx.attr.is_shell_of == CUSTOM_SHELL:
            fail("Shells must specify exactly one module")

        # if len(ctx.attr.deps) != 0:
        #     fail("Shells may not specify deps")

    else:
        for dep in ctx.attr.deps:
            if ShellInfo in dep and dep[ShellInfo].is_shell_of and not dep[ShellInfo].is_shell_of == CUSTOM_SHELL:
                fail("verilog_rtl_library may not depend on shells. Shells should only be included at top-level builds")
        for src in srcs:
            if "_shell" in src.basename:
                fail("Shell files should not be declared in an verilog_rtl_library. Use a verilog_rtl_shell instead. {} is declared in {}".format(src, ctx.label))

    gumi_path = ""
    if ctx.file.gumi_file_override:
        srcs = [ctx.file.gumi_file_override] + srcs
        gumi_path = runfiles_relative_short_path(ctx.file.gumi_file_override)
    elif ctx.attr.enable_gumi:
        gumi = ctx.actions.declare_file("gumi_{name}.vh".format(name = ctx.attr.name))
        gumi_content = []

        # Making this more unique than just gumi.basename.upper()
        # To avoid case where multiple directories define the same name for a verilog_rtl_library
        gumi_guard_value = gumi.short_path.replace("/", "_").replace(".", "_")
        gumi_guard = "__{}__".format(gumi_guard_value.upper())
        gumi_content.append("`ifndef {}".format(gumi_guard))
        gumi_content.append("  `define {}".format(gumi_guard))
        gumi_content.append("")
        gumi_content.append("")
        if ctx.attr.gumi_override:
            gumi_modules = ctx.attr.gumi_override
        else:
            gumi_modules = [module.basename[:-len(module.extension) - 1] for module in ctx.files.modules]
        for module_name in gumi_modules:
            gumi_name = "gumi_{}".format(module_name)
            gumi_content.append("  `ifndef {}".format(gumi_name))
            gumi_content.append("    `define {} {}".format(gumi_name, module_name))
            gumi_content.append("  `endif")
            gumi_content.append("")
        gumi_content.append("")
        gumi_content.append("")
        gumi_content.append("`endif // guard")

        ctx.actions.write(
            output = gumi,
            content = "\n".join(gumi_content),
        )

        srcs = [gumi] + srcs
        gumi_path = runfiles_relative_short_path(gumi)

    flist_content = create_flist_content(ctx, gumi_path = gumi_path, allow_library_discovery = False, makelib = ctx.attr.makelib)
    vcs_flist = ctx.outputs.flist
    if ctx.attr.makelib:
        vcs_flist = ctx.actions.declare_file(ctx.label.name + "_vcs.f")
        ctx.actions.write(
            output = vcs_flist,
            content = "\n".join(create_flist_content(ctx, gumi_path = gumi_path, allow_library_discovery = False)),
        )

    last_module = None
    for m in ctx.files.modules:
        last_module = m
    for m in ctx.files.lib_files:
        last_module = m
    for m in ctx.files.direct:
        last_module = m

    ctx.actions.write(
        output = ctx.outputs.flist,
        content = "\n".join(flist_content),
    )

    trans_srcs = get_transitive_srcs(srcs, ctx.attr.deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs([ctx.outputs.flist], ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    trans_vcs_flists = get_transitive_srcs(
        [vcs_flist],
        ctx.attr.deps,
        VerilogInfo,
        "transitive_vcs_flists",
        allow_other_outputs = False,
        fallback_attr_name = "transitive_flists",
    )
    trans_dpi = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_dpi", allow_other_outputs = False)

    runfiles = ctx.runfiles(transitive_files = depset(transitive = [trans_srcs, trans_flists, trans_vcs_flists, trans_dpi]))

    all_files = depset(transitive = [trans_srcs, trans_flists, trans_vcs_flists])

    return [
        ShellInfo(
            is_pkg = ctx.attr.is_pkg,
            is_shell_of = ctx.attr.is_shell_of,
            gumi_path = gumi_path,
        ),
        VerilogInfo(
            transitive_sources = trans_srcs,
            transitive_flists = trans_flists,
            transitive_vcs_flists = trans_vcs_flists,
            transitive_dpi = trans_dpi,
            last_module = last_module,
        ),
        DefaultInfo(
            files = all_files,
            runfiles = runfiles,
        ),
    ]

verilog_rtl_library = rule(
    doc = "A collection of RTL design files. Creates a generated flist file to be included later in a compile.",
    implementation = _verilog_rtl_library_impl,
    attrs = {
        "headers": attr.label_list(
            allow_files = True,
            doc = "Files that will be included into other files.\n" +
                  "A '+incdir' flag will be added for each source file's directory.",
        ),
        "modules": attr.label_list(
            allow_files = True,
            doc = "Verilog files containing a single module where the module name matches the file name.\n" +
                  "A '-y' flag will be added for each source file's directory.\n" +
                  "This is the preferred mechanism for specifying RTL modules.",
        ),
        "lib_files": attr.label_list(
            allow_files = True,
            doc = "Verilog library files containing multiple modules.\n" +
                  "A '-v' flag will be added for each file in this attribute.\n" +
                  "It is preferable to used the 'modules' attribute when possible because library files require parsing entire files to discover all modules.",
        ),
        "direct": attr.label_list(
            allow_files = True,
            doc = "Verilog files that must be put directly onto the command line.\n" +
                  "'modules' should be used instead of 'direct' wherever possible",
        ),
        "deps": attr.label_list(
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "no_synth": attr.bool(
            default = False,
            doc = "Compatibility marker for downstream synthesis aspects or consumers. Simulation targets continue to include this library.",
        ),
        "is_pkg": attr.bool(
            default = False,
            doc = "INTERNAL: Do not set in verilog_rtl_library instances.\n" +
                  "Used for internal bookkeeping for macros derived from verilog_rtl_library.\n" +
                  "Used to enforce naming conventions related to packages to encourage simple dependency graphs",
        ),
        "is_shell_of": attr.string(
            default = "",
            doc = "INTERNAL: Do not set in verilog_rtl_library instances.\n" +
                  "Used for internal bookkeeping for macros derived from verilog_rtl_library.\n" +
                  "If set, this library is represents a 'shell' of another module.\n" +
                  "Allows downstream test rules to specify this Label as a 'shell' to override another instance via the gumi system.",
        ),
        "enable_gumi": attr.bool(
            default = True,
            doc = "When set and gumi_file_override is absent, create an additional file containing default preprocessor values for the gumi system.",
        ),
        "gumi_file_override": attr.label(
            default = None,
            allow_single_file = True,
            doc = "Use a Label or file as the gumi definitions file instead of generating one.\n" +
                  "The override is retained in this library's transitive sources and runfiles.",
        ),
        "gumi_override": attr.string_list(
            doc = "A list of strings of module names to create gumi defines.\n" +
                  "If empty (default), the modules variable is used instead.\n" +
                  "Useful when using 'direct' or 'lib_files' or to limit the defines created when using a glob in 'modules'",
        ),
        "makelib": attr.string(
            default = "",
            doc = ("Compile this target into the named Xcelium library through -makelib/-endlib. " +
                   "VCS receives the same ordered sources through a separate -file boundary; VCS recompilation isolation is provided by -Mupdate and Partition Compile rather than Xcelium library syntax."),
        ),
    },
    outputs = {
        "flist": "%{name}.f",
    },
)

def verilog_rtl_pkg(
        name,
        direct,
        no_synth = False,
        deps = [],
        visibility = None):
    """A single Systemverilog package.

    This rule is a specialized case of verilog_rtl_library. Systemverilog
    packages should be placed into their own rule instance to limit cross
    dependencies. In general, a block may depend on another block's package but
    should not need to depend on all the modules in the block.

    Args:
      name: A unique name for this target.
      direct: The Systemverilog file containing the package.

        See verilog_rtl_library::direct.
      no_synth: Default False.

        Compatibility marker for downstream synthesis aspects or consumers.
        Simulation targets continue to include this package.
      deps: Other packages this target is dependent on.

        See verilog_rtl_library::deps.
      visibility: Bazel target visibility.
    """
    verilog_rtl_library(
        name = name,
        direct = direct,
        deps = deps,
        is_pkg = True,
        no_synth = no_synth,
        enable_gumi = False,
        visibility = visibility,
    )

def verilog_rtl_shell(
        name,
        module_to_shell_name,
        shell_module_label,
        deps = [],
        visibility = None):
    """An RTL shell has the same ports as another module.

    This rule is a specialized case of verilog_rtl_library.
    A 'shell' is similar to a 'stub' (empty module), but a shell may contain
    limited functionality. Frequent uses include:
      * Blackboxing hierarchy that will not be the target of testing
      * Replacing functionality with a simpler model (e.g. simulation-only memory models)

    Args:
      name: A unique name for this target.
      module_to_shell_name: The name of the module that will be replaced.

        When a downstream test uses this 'shell', a gumi define will be created using this name.

        When a shell needs to be hand-edited after generation If
        module_to_shell_name == 'custom', then all rules regarding shells are
        ignored and gumi shell defines are not thrown, allowing the user great
        power.
      shell_module_label: The Label or file containing the shell.

        The shell is selected explicitly by simulation consumers.
      deps: Other packages this target is dependent on.

        In general. shells should avoid having dependencies. Exceptions include
        necessary packages and possible a DV model to implement functional
        behavior.

        See verilog_rtl_library::deps.
      visibility: Bazel target visibility.
    """
    if not name.startswith(module_to_shell_name) and module_to_shell_name != CUSTOM_SHELL:
        fail("Shell name should start with the original module name: shell name='{}' original module='{}'".format(name, module_to_shell_name))
    verilog_rtl_library(
        name = name,
        modules = [shell_module_label],
        # Intentionally do not set deps here
        is_shell_of = module_to_shell_name,
        enable_gumi = False,
        deps = deps,
        visibility = visibility,
    )

def _verilog_rtl_unit_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    simulator = resolve_unit_test_simulator(ctx.attr.simulator, ctx.attr._unit_test_simulator)
    flist_field = "transitive_vcs_flists" if simulator == "VCS" else "transitive_flists"
    flists = get_transitive_srcs(
        [],
        ctx.attr.shells + ctx.attr.deps,
        VerilogInfo,
        flist_field,
        fallback_attr_name = "transitive_flists" if simulator == "VCS" else None,
    )
    flists_list = flists.to_list()

    top = ""
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            top = runfiles_relative_short_path(dep[VerilogInfo].last_module)
            top_base_name = dep[VerilogInfo].last_module.basename.split(".")[0]

    if top == "":
        fail("verilog_rtl_unit_test {} could not determine the top module from the target's dependencies".format(ctx.label))

    pre_fa = []
    for key, value in gather_shell_defines(ctx.attr.shells).items():
        if simulator == "VCS":
            pre_fa.append("+define+{}{}".format(key, value))
        else:
            pre_fa.append("-define {}{}".format(key, value))

    target_pre_flist_args = ctx.attr.pre_flist_args
    target_post_flist_args = ctx.attr.post_flist_args
    runtime_args = ctx.attr.run_args
    if simulator == "VCS":
        partitioned_pre_args = partition_vcs_unit_test_args(target_pre_flist_args)
        partitioned_post_args = partition_vcs_unit_test_args(target_post_flist_args)
        target_pre_flist_args = partitioned_pre_args.compile_args
        target_post_flist_args = partitioned_post_args.compile_args
        runtime_args = partitioned_pre_args.runtime_args + partitioned_post_args.runtime_args + runtime_args
    else:
        target_post_flist_args = target_post_flist_args + runtime_args

    pre_fa.extend(target_pre_flist_args)
    template_pre_fa = " ".join(pre_fa)
    if simulator == "XRUN":
        template_pre_fa = "\n".join(["    \\"] + ["  {} \\".format(arg) for arg in pre_fa] + ["   \\"])

    post_fa = " ".join(target_post_flist_args)

    ut_sim_template = _resolve_unit_test_default_file(
        simulator,
        ctx.file.ut_sim_template,
        ctx.file._ut_sim_template_xrun,
        ctx.file._ut_sim_template_vcs,
    )
    if simulator == "VCS" and ctx.file.ut_sim_template.short_path == ctx.file._ut_sim_template_svunit_xrun.short_path:
        fail("verilog_rtl_unit_test {} uses the Xcelium-only SVUnit template; set simulator = 'XRUN' or provide a VCS-compatible custom template".format(ctx.label))
    ut_sim_waves_template = _resolve_unit_test_default_file(
        simulator,
        ctx.file.ut_sim_waves_template,
        ctx.file._ut_sim_waves_template_xrun,
        ctx.file._ut_sim_waves_template_vcs,
    )
    simulator_command = ctx.attr.command_override[ToolEncapsulationInfo].command
    if simulator == "VCS" and ctx.attr.command_override.label == ctx.attr._command_override_xrun.label:
        simulator_command = ctx.attr._command_override_vcs[ToolEncapsulationInfo].command
    wave_viewer_command = ctx.attr.wave_viewer_command[ToolEncapsulationInfo].command
    if simulator == "VCS" and ctx.attr.wave_viewer_command.label == ctx.attr._wave_viewer_command_xrun.label:
        wave_viewer_command = ctx.attr._wave_viewer_command_vcs[ToolEncapsulationInfo].command
    filelist_flag = "-file" if simulator == "VCS" else "-f"

    waves_cmd = ctx.actions.declare_file(ctx.label.name + "_waves.tcl")
    ctx.actions.expand_template(
        template = ut_sim_waves_template,
        output = waves_cmd,
        substitutions = {
            "{TOP_BASE_NAME}": top_base_name,  # buildifier: disable=uninitialized
        },
    )

    compile_args = None
    if simulator == "VCS":
        compile_args = ctx.actions.declare_file(ctx.label.name + "_compile_args.f")
        ctx.actions.expand_template(
            template = ctx.file._compile_args_template_vcs,
            output = compile_args,
            substitutions = {
                "{DEFINES}": "\n".join(pre_fa),
                "{FLISTS}": "\n".join(["{} {}".format(filelist_flag, runfiles_relative_short_path(f)) for f in flists_list]),
                "{POST_FLIST_ARGS}": post_fa,
                "{TOP_BASE_NAME}": top_base_name,  # buildifier: disable=uninitialized
            },
        )

    ctx.actions.expand_template(
        template = ut_sim_template,
        output = ctx.outputs.executable,
        substitutions = {
            "{SIMULATOR_COMMAND}": simulator_command,
            "{SIMULATOR_RUNNER}": ctx.attr._vcs_unit_test_runner[ToolEncapsulationInfo].command if simulator == "VCS" else "",
            "{WAVE_VIEWER_COMMAND}": wave_viewer_command,
            "{FLISTS}": " ".join(["{} {}".format(filelist_flag, runfiles_relative_short_path(f)) for f in flists_list]),
            "{TOP}": top,
            "{PRE_FLIST_ARGS}": template_pre_fa,
            "{POST_FLIST_ARGS}": post_fa,
            "{RUN_ARGS}": " ".join(runtime_args),
            "{COMPILE_ARGS_FILE}": runfiles_relative_short_path(compile_args) if compile_args else "",
            "{WAVES_RENDER_CMD_PATH}": runfiles_relative_short_path(waves_cmd),
        },
        is_executable = True,
    )

    generated_files = [waves_cmd]
    if compile_args:
        generated_files.append(compile_args)
    runfiles = merge_default_runfiles(
        ctx,
        files = flists_list + srcs_list + ctx.files.data + ctx.files.shells + generated_files,
        targets = ctx.attr.shells + ctx.attr.deps + ctx.attr.data,
    )
    return [DefaultInfo(
        runfiles = runfiles,
    )]

verilog_rtl_unit_test = rule(
    doc = """Compile and simulate a verilog_rtl_library.

    Allows a designer to write small unit/directed tests which can be included in regression.

    This rule is capable of running SVUnit regressions as well. See ut_sim_template attribute.

    This unit test can either immediately launch a waveform viewer, or it can render a waveform database which can be loaded separately.
    To launch the waveform viewer after the test completes, run the following: 'bazel run <target> -- --launch &'.
    To render a database without launching a viewer, run the following: 'bazel run <target> -- --waves'.
    Any other unknown options will be passed directly to the simulator, for example: 'bazel run <target> -- --waves +my_arg=4'.
    Wave rendering is currently available only with XRUN; VCS wave commands are retained but disabled.

    Typically, an additional verilog_rtl_library containing 'unit_test_top.sv'
    is created. This unit_test_top will be dependent on the DUT top, and will
    be the only entry in the `deps` attribute list provided to verilog_rtl_unit_test.
    """,
    implementation = _verilog_rtl_unit_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "simulator": attr.string(
            values = ["", "XRUN", "VCS"],
            doc = "Simulator to use for this one-step RTL unit test. When omitted, verilog_unit_test_simulator selects XRUN or VCS.\n",
        ),
        "run_args": attr.string_list(
            doc = "Additional arguments passed only to simulation runtime. With VCS, legacy runtime plusargs in pre_flist_args or post_flist_args are also passed to simv.\n",
        ),
        "ut_sim_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_unit_test.sh.template"),
            doc = "The template to generate the script to run the test.\n" +
                  "Also available is a [SVUnit](http://agilesoc.com/open-source-projects/svunit/) test template: @rules_verilog//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template\n" +
                  "If using the SVUnit template, you may also want to throw:\n" +
                  "```" +
                  "    post_flist_args = [\n" +
                  "    \"--directory <path_to_test_directory_from_workspace>\",\n" +
                  " ]," +
                  "```\n",
        ),
        "ut_sim_waves_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_unit_test_waves.tcl.template"),
            doc = "The template to generate the waves command script to run in the test.\n" +
                  "When using the SVUnit ut_sim_template or a custom SVUnit invocation, the default verilog_rtl_unit_test_waves.tcl.template will not work. " +
                  "You must either write your own waves script or use the SVUnit waves template: " +
                  "@rules_verilog//vendors/cadence:verilog_rtl_unit_test_svunit_waves.tcl.template\n",
        ),
        "_ut_sim_template_xrun": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_unit_test.sh.template"),
        ),
        "_ut_sim_template_vcs": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/synopsys:verilog_rtl_unit_test.sh.template"),
        ),
        "_ut_sim_template_svunit_xrun": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template"),
        ),
        "_ut_sim_waves_template_xrun": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_unit_test_waves.tcl.template"),
        ),
        "_ut_sim_waves_template_vcs": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/synopsys:verilog_rtl_unit_test_waves.tcl.template"),
        ),
        "_compile_args_template_vcs": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/synopsys:verilog_rtl_unit_test_compile_args.f.template"),
        ),
        "command_override": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_unit_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles.\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:verilog_rtl_unit_test_command="runmod -t xrun --"',
        ),
        "_command_override_xrun": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_unit_test_command"),
        ),
        "_command_override_vcs": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_unit_test_command_vcs"),
        ),
        "wave_viewer_command": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_wave_viewer_command"),
            doc = "Allows custom override of waveform viewer command in the event of wrapping via modulefiles.\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:verilog_rtl_wave_viewer_command="runmod xrun --"\n',
        ),
        "_wave_viewer_command_xrun": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_wave_viewer_command"),
        ),
        "_wave_viewer_command_vcs": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_wave_viewer_command_vcs"),
        ),
        "_unit_test_simulator": attr.label(
            default = Label("@rules_verilog//:verilog_unit_test_simulator"),
        ),
        "_vcs_unit_test_runner": attr.label(
            default = Label("@rules_verilog//:verilog_vcs_unit_test_runner"),
        ),
        "data": attr.label_list(
            allow_files = True,
            doc = "Non-verilog dependencies. Useful when reading in data files as stimulus/prediction.",
        ),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "pre_flist_args": attr.string_list(
            doc = "Additional command line arguments to be placed after the simulator binary but before the flist arguments.\n" +
                  "See ut_sim_template attribute for exact layout." +
                  "For defines to have effect, they must be declared in pre_flist_args not post_flist_args. " +
                  "With VCS, legacy '-define NAME' entries become '+define+NAME'; Xcelium-only debug/wave flags are omitted, and non-compiler plusargs are passed to simv.",
        ),
        "post_flist_args": attr.string_list(
            doc = "Additional command line arguments to be placed after the flist arguments\n" +
                  "See ut_sim_template attribute for exact layout. " +
                  "With VCS, legacy '-define NAME' entries become '+define+NAME'; Xcelium-only debug/wave flags are omitted, and non-compiler plusargs are passed to simv.",
        ),
    },
    test = True,
)

def _verilog_rtl_lint_test_impl(ctx):
    simulator = resolve_unit_test_simulator(ctx.attr.simulator, ctx.attr._unit_test_simulator)
    run_template = _resolve_unit_test_default_file(
        simulator,
        ctx.file.run_template,
        ctx.file._run_template_xrun_default,
        ctx.file._run_template_vcs_default,
    )
    command_template = _resolve_unit_test_default_file(
        simulator,
        ctx.file.command_template,
        ctx.file._command_template_xrun_default,
        ctx.file._command_template_vcs_default,
    )
    lint_parser = _resolve_label_default_file(
        simulator,
        ctx.attr.lint_parser.label,
        "@rules_verilog//bin:lint_parser_hal",
        ctx.files.lint_parser[0],
        ctx.file._lint_parser_vcs_default,
    )
    rulefile = None
    if len(ctx.files.rulefile) > 1:
        fail("Only one rulefile allowed, but {} has several rulefiles".format(ctx.label))
    if len(ctx.files.rulefile) == 1:
        rulefile = ctx.files.rulefile[0]
    elif simulator == "VCS":
        rulefile = ctx.file._rulefile_vcs_default
    else:
        fail("verilog_rtl_lint_test {} requires rulefile when simulator = 'XRUN'".format(ctx.label))

    flist_field = "transitive_vcs_flists" if simulator == "VCS" else "transitive_flists"
    trans_flists = get_transitive_srcs(
        [],
        ctx.attr.shells + ctx.attr.deps,
        VerilogInfo,
        flist_field,
        allow_other_outputs = False,
        fallback_attr_name = "transitive_flists",
    )

    # This is a workaround for an issue with using -define in Ascent and will be removed once the Ascent issue is fixed
    # See github issue #24
    shell_defines_string = "-define {}{}"
    attr_defines_string = "-define {}{}"
    if simulator == "VCS" or str(ctx.attr.run_template.label) == "@rules_verilog//vendors/real_intent:verilog_rtl_lint_test.sh.template":
        shell_defines_string = "+define+{}{}"
        attr_defines_string = "+define+{}{}"

    defines = [shell_defines_string.format("LINT", "")]
    defines.extend([shell_defines_string.format(key, value) for key, value in gather_shell_defines(ctx.attr.shells).items()])
    defines.extend([attr_defines_string.format(key, value) for key, value in ctx.attr.defines.items()])

    top_path = ""
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            top_path = runfiles_relative_short_path(dep[VerilogInfo].last_module)

    if top_path == "":
        fail("verilog_rtl_lint_test {} could not determine the top module from the target's dependencies".format(ctx.label))

    ctx.actions.expand_template(
        template = command_template,
        output = ctx.outputs.command_script,
        substitutions = {
            "{RULEFILE}": runfiles_relative_short_path(rulefile),
            "{DEFINES}": " ".join(defines),
            "{FLISTS}": " ".join(["{} {}".format("-file" if simulator == "VCS" else "-f", runfiles_relative_short_path(f)) for f in trans_flists.to_list()]),
            "{TOP_PATH}": top_path,
            "{INST_TOP}": ctx.attr.top,
            "{LINT_PARSER}": runfiles_relative_short_path(lint_parser),
        },
    )

    simulator_command = ctx.attr._command_override[ToolEncapsulationInfo].command
    if simulator == "VCS":
        simulator_command = ctx.attr._command_override_vcs[ToolEncapsulationInfo].command

    ctx.actions.expand_template(
        template = run_template,
        output = ctx.outputs.executable,
        substitutions = {
            "{SIMULATOR_COMMAND}": simulator_command,
            "{COMMAND_SCRIPT}": runfiles_relative_short_path(ctx.outputs.command_script),
            "{DEFINES}": " ".join(defines),
            "{FLISTS}": " ".join(["{} {}".format("-file" if simulator == "VCS" else "-f", runfiles_relative_short_path(f)) for f in trans_flists.to_list()]),
            "{TOP_PATH}": top_path,
            "{DESIGN_INFO}": " ".join([runfiles_relative_short_path(design_info) for design_info in ctx.files.design_info]),
            "{RULEFILE}": runfiles_relative_short_path(rulefile),
            "{INST_TOP}": ctx.attr.top,
            "{LINT_PARSER}": runfiles_relative_short_path(lint_parser),
            "{LINT_PARSER_LIB}": runfiles_relative_short_path(ctx.files._lint_parser_lib[0])[:-len(ctx.files._lint_parser_lib[0].basename) - 1],
            "{WAIVER_DIRECT}": ctx.attr.waiver_direct,
        },
    )

    trans_flists = get_transitive_srcs(
        [],
        ctx.attr.shells + ctx.attr.deps,
        VerilogInfo,
        flist_field,
        allow_other_outputs = False,
        fallback_attr_name = "transitive_flists",
    )
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)

    lint_runfile_targets = ctx.attr.shells + ctx.attr.deps + ctx.attr.design_info + [
        ctx.attr.lint_parser,
        ctx.attr._lint_parser_lib,
        ctx.attr._lint_parser_vcs_default,
        ctx.attr._rulefile_vcs_default,
    ]
    if ctx.attr.rulefile:
        lint_runfile_targets.append(ctx.attr.rulefile)
    runfiles = merge_default_runfiles(
        ctx,
        files = trans_srcs.to_list() + trans_flists.to_list() + ctx.files.design_info + [rulefile, lint_parser] + ctx.files._lint_parser_lib + [ctx.outputs.command_script],
        targets = lint_runfile_targets,
    )

    return [
        DefaultInfo(runfiles = runfiles),
    ]

verilog_rtl_lint_test = rule(
    doc = """Compile and run lint on target

    This rule was originally written for Cadence HAL to be run under xcelium. As such, it
    is not entirely generic. It also uses a log post-processor
    (passed in by the lint_parser attribute) to allow for easier waiving of warnings.

    When `simulator = "VCS"`, the rule automatically switches to built-in
    Synopsys defaults for the launcher, lint command file, parser, and default
    rulefile. Projects may still override these assets if they need a more
    opinionated local policy.

    The DUT must have no unwaived warning/errors in order for this rule to
    pass. The intended philosophy is for blocks to maintain a clean lint status
    throughout the lifecycle of the project, not to run lint as a checklist
    item towards the end of the project.

    There are several attributes in this rule that must be kept in sync.
    run_template, rulefile, lint_parser, and command_template must use the associated
    files for each vendor. The default values auto-select between the built-in
    Cadence and Synopsys sets based on the simulator attribute. If an instance
    overrides any of these vendor-specific values, it should override the full set.

    """,
    implementation = _verilog_rtl_lint_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "simulator": attr.string(
            values = ["", "XRUN", "VCS"],
            doc = "Simulator launcher to use for this lint test. When omitted, verilog_unit_test_simulator selects XRUN or VCS. XRUN uses the built-in Cadence defaults. VCS automatically switches to the built-in Synopsys launcher, lint command file, parser, and default rulefile.\n",
        ),
        "run_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_lint_test.sh.template"),
            doc = "The template to generate the script to run the lint test.\n" +
                  "The command templates are located at " +
                  "@rules_verilog//vendors/<vendor name>/verilog_rtl_lint_test.tcl.template\n",
        ),
        "rulefile": attr.label(
            allow_single_file = True,
            doc = "The rules configuration file for this lint run. rules_verilog doesn't provide a reference rulefile, " +
                  "each project that uses rules_verilog may write their own tool-specific rulefile.\n" +
                  "When omitted and simulator = VCS, rules_verilog uses a built-in Synopsys default lint opts file.\n" +
                  "When simulator = XRUN, a project-specific Cadence/HAL rulefile is still required.\n" +
                  "Example HAL rulefile: https://github.com/freecores/t6507lp/blob/ca7d7ea779082900699310db459a544133fe258a/lint/run/hal.def",
        ),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "top": attr.string(
            doc = "The name of the top-level module for this lint run",
            mandatory = True,
        ),
        "design_info": attr.label_list(
            allow_files = True,
            doc = "A Cadence design_info file to add additional lint rule/waivers",
        ),
        "defines": attr.string_dict(
            allow_empty = True,
            doc = "List of additional \\`defines for this lint run.\nLINT is always defined by default\n" +
                  "If a define is only for control and has no value, " +
                  "e.g. \\`define USE_AXI, the dictionary entry key should be \"USE_AXI\" and the value should be the empty string.\n" +
                  "If a define needs a value, e.g. \\`define WIDTH 8, the dictionary value must start with '=', e.g. '=8'",
        ),
        "lint_parser": attr.label(
            allow_files = True,
            default = "@rules_verilog//bin:lint_parser_hal",
            doc = "Post processor for lint logs allowing for easier waiving of warnings.\n" +
                  "Parsers for HAL, Ascent, and VCS are included in rules_verilog release at " +
                  "@rules_verilog//bin:lint_parser_(hal|ascent|vcs)\n" +
                  "When left at the default HAL label and simulator = VCS, the rule automatically switches to the built-in VCS parser.",
        ),
        "waiver_direct": attr.string(
            doc = "Lint waiver python regex to apply directly to a lint message. This is sometimes needed to work around cases when HAL has formatting errors in xrun.log.xml that cause problems for the lint parser",
        ),
        "command_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_lint_cmds.tcl.template"),
            doc = "The template to generate the command script for this lint test.\n" +
                  "The command templates are located at " +
                  "@rules_verilog//vendors/<vendor name>/verilog_rtl_lint_cmds.tcl.template\n",
        ),
        "_command_override": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_lint_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:verilog_rtl_lint_test_command="runmod -t xrun --"',
        ),
        "_command_override_vcs": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_lint_test_command_vcs"),
            doc = "Default command encapsulation for VCS rtl lint tests.",
        ),
        "_unit_test_simulator": attr.label(
            default = Label("@rules_verilog//:verilog_unit_test_simulator"),
        ),
        "_run_template_xrun_default": attr.label(
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_lint_test.sh.template"),
            allow_single_file = True,
        ),
        "_run_template_vcs_default": attr.label(
            default = Label("@rules_verilog//vendors/synopsys:verilog_rtl_lint_test.sh.template"),
            allow_single_file = True,
        ),
        "_command_template_xrun_default": attr.label(
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_lint_cmds.tcl.template"),
            allow_single_file = True,
        ),
        "_command_template_vcs_default": attr.label(
            default = Label("@rules_verilog//vendors/synopsys:verilog_rtl_lint_cmds.tcl.template"),
            allow_single_file = True,
        ),
        "_lint_parser_vcs_default": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//bin:lint_parser_vcs.py",
        ),
        "_rulefile_vcs_default": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/synopsys:verilog_rtl_lint_default_opts.f"),
        ),
        "_lint_parser_lib": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//lib:cmn_logging",
            doc = "Python library dir needed by lint parser script.\n" +
                  "Using a private attribute instead of something cleaner\n" +
                  "because I cannot find a way to create File objects\n" +
                  "from Label objects to be used with ctx.runfiles",
        ),
    },
    outputs = {
        "command_script": "%{name}_cmds.tcl",
    },
    test = True,
)

def _verilog_rtl_cdc_test_impl(ctx):
    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)

    # The run script is simple, the tcl command file has the interesting stuff
    ctx.actions.expand_template(
        template = ctx.file.bash_template,
        output = ctx.outputs.executable,
        substitutions = {
            "{CDC_COMMAND}": ctx.attr._command_override[ToolEncapsulationInfo].command,
            "{PREAMBLE_CMDS}": runfiles_relative_short_path(ctx.outputs.preamble_cmds),
            "{CMD_FILES}": " ".join([runfiles_relative_short_path(cmd_file) for cmd_file in ctx.files.cmd_files]),
            "{EPILOGUE_CMDS}": runfiles_relative_short_path(ctx.outputs.epilogue_cmds),
        },
    )

    defines = ["+define+LINT", "+define+CDC"]

    defines.extend(["+define+{}{}".format(key, value) for key, value in ctx.attr.defines.items()])
    for key, value in gather_shell_defines(ctx.attr.shells).items():
        defines.append("+define+{}{}".format(key, value))

    top_path = ""
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            top_path = "  {}".format(runfiles_relative_short_path(dep[VerilogInfo].last_module))
    if top_path == "":
        fail("verilog_rtl_cdc_test {} could not determine the top module from the target's dependencies".format(ctx.label))

    bbox_modules_cmd = ""
    if ctx.attr.bbox_modules:
        bbox_modules_cmd = "-bbox_m {" + "{}".format(" ".join(ctx.attr.bbox_modules)) + "}"

    bbox_array_size_cmd = ""
    if ctx.attr.bbox_array_size < 0:
        fail("verilog_rtl_cdc_test {} was specified with a negative bbox_array_size".format(ctx.label))
    elif ctx.attr.bbox_array_size > 0:
        bbox_array_size_cmd = "-bbox_a {}".format(ctx.attr.bbox_array_size)

    ctx.actions.expand_template(
        template = ctx.file.preamble_template,
        output = ctx.outputs.preamble_cmds,
        substitutions = {
            "{DEFINES}": " ".join(defines),
            "{FLISTS}": " ".join(["-f {}".format(runfiles_relative_short_path(f)) for f in trans_flists.to_list()]),
            "{TOP_PATH}": top_path,
            "{INST_TOP}": ctx.attr.top,
            "{BBOX_MODULES_CMD}": bbox_modules_cmd,
            "{BBOX_ARRAY_SIZE_CMD}": bbox_array_size_cmd,
        },
    )

    ctx.actions.expand_template(
        template = ctx.file.epilogue_template,
        output = ctx.outputs.epilogue_cmds,
        substitutions = {},
    )

    runfiles = merge_default_runfiles(
        ctx,
        files = [ctx.outputs.preamble_cmds, ctx.outputs.epilogue_cmds] + trans_srcs.to_list() + trans_flists.to_list() + ctx.files.cmd_files,
        targets = ctx.attr.shells + ctx.attr.deps + ctx.attr.cmd_files,
    )

    return [
        DefaultInfo(runfiles = runfiles),
    ]

verilog_rtl_cdc_test = rule(
    doc = "Run Jaspergold CDC on a verilog_rtl_library.",
    implementation = _verilog_rtl_cdc_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "preamble_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_cdc_preamble_cmds.tcl.template"),
            doc = "The template to generate the initial commands (the preamble) for this cdc test.\n",
        ),
        "epilogue_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_cdc_epilogue_cmds.tcl.template"),
            doc = "The template to generate the final reporting commands for this cdc test.\n",
        ),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "top": attr.string(
            doc = "The name of the top-level module for this cdc run",
            mandatory = True,
        ),
        "defines": attr.string_dict(
            allow_empty = True,
            doc = "List of additional \\`defines for this cdc run.\nLINT and CDC are always defined\n" +
                  "If a define is only for control and has no value, " +
                  "e.g. \\`define USE_AXI, the dictionary entry key should be \"USE_AXI\" and the value should be the empty string.\n" +
                  "If a define needs a value, e.g. \\`define WIDTH 8, the dictionary value must start with '=', e.g. '=8'",
        ),
        "bbox_modules": attr.string_list(
            allow_empty = True,
            default = [],
            doc = "List of modules to black box",
        ),
        "bbox_array_size": attr.int(
            default = 0,
            doc = "Black box any RTL array greater than the specified size. If the value of this attribute is 0, the CDC tool will use the default size",
        ),
        "cmd_files": attr.label_list(
            allow_files = True,
            doc = "A list of tcl files containing commands to run. Multiple files are allowed to facilitate separating common project commands and block-specific commands.",
            mandatory = True,
        ),
        "bash_template": attr.label(
            allow_single_file = True,
            default = Label("//vendors/cadence:verilog_rtl_cdc_test.sh.template"),
            doc = "The template for the generated bash script which will run the case.",
        ),
        "_command_override": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_cdc_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:rtl_cdc_test_command="runmod -t jg --"',
        ),
    },
    outputs = {
        "preamble_cmds": "%{name}_preamble_cmds.tcl",
        "epilogue_cmds": "%{name}_epilogue_cmds.tcl",
    },
    test = True,
)
