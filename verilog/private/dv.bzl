"""Rules for building DV infrastructure."""

load(":verilog.bzl", "ToolEncapsulationInfo", "VerilogInfo", "flists_to_arguments", "gather_shell_defines", "get_transitive_srcs")
load("@//deps:gatesim_modes_list.bzl","GATESIM_MODES")

DVTestInfo = provider(fields = {
    "sim_opts": "Simulation :options to carry forward.",
    "uvm_testname": "UVM Test Name; passed to simulator via plusarg +UVM_TESTNAME.",
    "tb": "The verilog_dv_tb (verilog compile) associated with this test. Must be a Label of type verilog_dv_tb.",
    "tags": "Additional tags to be able to filter in simmer.",
    "timeout": "Duration in minutes before the test will be killed due to timeout.",
    "pre_run": "Bazel run command that can be executed immediately before dv_tb simulation.",
    "description": "Test scenario descriptions.",
})

DVTBInfo = provider(fields = {
    "ccf": "Coverage config file.",
})

def _verilog_dv_test_base_cfg_impl(ctx):
    parent_uvm_testnames = [dep[DVTestInfo].uvm_testname for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "uvm_testname")]
    parent_tbs = [dep[DVTestInfo].tb for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "tb")]
    parent_timeouts = [dep[DVTestInfo].timeout for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "timeout")]
    parent_pre_run = [dep[DVTestInfo].pre_run for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "pre_run")]

    sim_opts = {}

    # Each successive dependency may override previous deps
    for dep in ctx.attr.inherits:
        sim_opts.update(dep[DVTestInfo].sim_opts)

    # This rule instance may override previous sim_opts
    sim_opts.update(ctx.attr.sim_opts)

    provider_args = {}

    uvm_testname = None
    if ctx.attr.uvm_testname:
        uvm_testname = ctx.attr.uvm_testname
    elif len(parent_uvm_testnames):
        uvm_testname = parent_uvm_testnames[0]
    else:
        uvm_testname = ctx.attr.name

    timeout = None
    if ctx.attr.timeout:
        timeout = ctx.attr.timeout
    elif len(parent_timeouts):
        timeout = parent_timeouts[0]

    tb = None
    if ctx.attr.tb:
        tb = ctx.attr.tb
    else:
        tb = parent_tbs[0]

    pre_run = None
    if ctx.attr.pre_run:
        pre_run = ctx.attr.pre_run
    elif len(parent_pre_run):
        pre_run = parent_pre_run[0]

    description = None
    if ctx.attr.description:
        description = ctx.attr.description

    provider_args["uvm_testname"] = uvm_testname
    provider_args["tb"] = tb
    provider_args["timeout"] = timeout
    provider_args["sim_opts"] = sim_opts
    provider_args["tags"] = ctx.attr.tags
    provider_args["pre_run"] = pre_run
    provider_args["description"] = description

    for socket_name, socket_command in ctx.attr.sockets.items():
        if "{socket_file}" not in socket_command:
            fail("socket {} did not have {{socket_file}} in socket_command".format(socket_name))

    dynamic_args = {
        "sockets": ctx.attr.sockets,
        "timeout": timeout,
        "sim_opts": sim_opts,
        "uvm_testname": uvm_testname,
        "tags": ctx.attr.tags,
        "pre_run": pre_run,
    }
    out = ctx.outputs.dynamic_args
    ctx.actions.write(
        output = out,
        content = str(dynamic_args),
    )
    return [DVTestInfo(**provider_args)]

verilog_dv_test_base_cfg = rule(
    doc = """A DV test configuration.

    This is not a executable target. It generates multiple files which may then
    be used by simmer (the wrapping tool to invoke the simulator).
    """,
    implementation = _verilog_dv_test_base_cfg_impl,
    attrs = {
        "abstract": attr.bool(
            default = False,
            doc = "When True, this configuration is abstract and does not represent a complete configuration.\n" +
                  "It is not intended to be executed. It is only intended to be used as a base for other test configurations to inherit from.\n" +
                  "See 'inherits' attribute.\n",
        ),
        "inherits": attr.label_list(
            doc = "Inherit configurations from other verilog_dv_test_cfg targets.\n" +
                  "Entries later in the list will override arguments set by previous inherits entries.\n" +
                  "Only attributes noted as inheritable in documentation may be inherited.\n" +
                  "Any field explicitly set in this rule will override values set via inheritance.",
        ),
        "uvm_testname": attr.string(
            doc = "UVM testname eventually passed to simulator via plusarg +UVM_TESTNAME.\n" +
                  "This attribute is inheritable. See 'inherits' attribute.\n",
        ),
        "tb": attr.label(
            doc = "The testbench to run this test on. This label must be a 'verilog_dv_tb' target." +
                  "This attribute is inheritable. See 'inherits' attribute.\n" +
                  "Future: Allow tb to be a list of labels to allow a test to run on multiple verilog_dv_tb",
        ),
        "sim_opts": attr.string_dict(
            doc = "Additional simulation options. These are 'runtime' arguments. Preprocessor or compiler directives will not take effect.\n" +
                  "The (key, value) pairs are joined without additional characters." +
                  "For unary arguments (e.g. +DISABLE_SCOREBOARD), set the value to be the empty string.\n" +
                  "For arguments with a value (e.g. +UVM_VERBOSITY=UVM_MEDIUM), add an '=' as a suffix to the key.\n" +
                  "This attribute is inheritable. See 'inherits' attribute.\n" +
                  "Unlike other inheritable attributes, values in sim_opts are not entirely overridden. Instead, the dictionary is 'updated' with new values at each successive level.\n" +
                  "This allows for the override of individual simopts for finer-grained control.",
        ),
        "no_run": attr.bool(
            default = False,
            doc = "Set to True to skip running this test.\n" +
                  "This flag is not used by bazel but is used as a query filter by simmer." +
                  "TODO: Deprecate this flag in favor of using built-in tags.",
        ),
        "sockets": attr.string_dict(
            doc = "Dictionary mapping of socket_name to socket_command.\n" +
                  "Simmer has the ability to spawn parallel processes to the primary simulation that are connected via sockets.\n" +
                  "For each entry in the dictionary, simmer will create a separate process and pass a unique temporary file path to both the simulator and the socket_command.\n" +
                  "The socket name is a short identifier that will be passed as \"+SOCKET__<socket_name>=<socket_file>\" to the simulator.\n" +
                  "The socket_file is a path to a unique temporary file in the simulation results directory created by simmer.\n" +
                  "The socket_command is a bash command that must contain a python string formatter of \"{socket_file}\".\n" +
                  "The socket_command will be run from the root of the project tree.",
        ),
        "pre_run": attr.string(
            doc = "Simmer has the ability to execute a user-specified bazel run command before starting the RTL simulation process.\n" +
                  "This attribute is where the user can define that bazel run command, on a per-test basis.\n" +
                  "For example, if the use wants to run 'bazel run //foo:bar' before their simulation, set this attribute to '//foo:bar'.",
        ),
        "timeout": attr.int(
            default = -1,
            doc = "Duration in minutes before the test will be killed due to timeout.\n" +
                  "This option is inheritable.",
        ),
        "description": attr.string(
            doc = "The test scenario descriptions"
        ),
    },
    outputs = {
        "dynamic_args": "%{name}_dynamic_args.py",
    },
)

def verilog_dv_test_cfg(name = None, tags = None, abstract = None, inherits = None, uvm_testname = None, tb = None, sim_opts = None, no_run = None, sockets = None, pre_run = None, timeout = None, description = None, gls_tb = None, pre_opts = None, post_opts = None):
    #get testcase arguments
    params = {}
    if name != None:
        params['name'] = name
    if abstract != None:
        params['abstract'] = abstract
    if inherits != None:
        params['inherits'] = inherits
    if uvm_testname != None:
        params['uvm_testname'] = uvm_testname
    if tb != None:
        params['tb'] = tb
    if no_run != None:
        params['no_run'] = no_run
    if sockets != None:
        params['sockets'] = sockets
    if pre_run != None:
        params['pre_run'] = pre_run
    if timeout != None:
        params['timeout'] = timeout
    if description != None:
        params['description'] = description

    #bazel case for pre_sim
    if pre_opts != None:
        pre_sim_opts = sim_opts + pre_opts
    else:
        pre_sim_opts = sim_opts

    params['sim_opts'] = pre_sim_opts

    #bazel case for pre_sim
    #remove "gatesim" keyword in tags when pre_sim
    temp_tags = []
    if tags != None:
        for tag in tags:
            if tag != "gatesim":
                temp_tags.append(tag)
    #replace temp_tags without "gatesim" with params['tags']
    params['tags'] = temp_tags
    verilog_dv_test_base_cfg(**params)

    #bazel case for post_sim
    if tags != None and "gatesim" in tags:
        if post_opts != None:
            post_sim_opts = sim_opts + post_opts
        else:
            post_sim_opts = sim_opts

        params['sim_opts'] = post_sim_opts

        #remove "ci_gate", "nightly", "weekly" keyword in tags when post_sim
        temp_tags = []
        for tag in tags:
            if tag != "ci_gate" and tag != "nightly" and tag != "weekly":
                temp_tags.append(tag)
        params['tags'] = temp_tags

        #add suffix for name,tb,inherits according gatesim corner to create post_sim testcase
        for corner in GATESIM_MODES:
            params['name'] = name + "_" + corner
            if inherits != None:
                for inherit in inherits:
                    params['inherits'] = [inherit + "_" + corner]
            #determin gatesim tb when gls_tb is transmited
            if gls_tb != None:
                params['tb'] = gls_tb + "_" + corner
            elif tb != None:
                params['tb'] = tb + "_" + corner
            verilog_dv_test_base_cfg(**params)

def _verilog_dv_library_impl(ctx):
    if ctx.attr.incdir:
        # Using dirname may result in bazel-out included in path
        directories = depset([f.short_path[:-len(f.basename) - 1] for f in ctx.files.srcs]).to_list()
    else:
        directories = []

    # # Add output files from direct dependencies (from genrules)
    srcs = depset(ctx.files.srcs, transitive = [dep[DefaultInfo].files for dep in ctx.attr.deps if VerilogInfo not in dep])

    if len(ctx.files.in_flist):
        in_flist = ctx.files.in_flist
    else:
        in_flist = ctx.files.srcs

    content = []
    for d in directories:
        if d == "":
            d = "."
        content.append("+incdir+{}".format(d))
    for f in in_flist:
        content.append(f.short_path)

    all_sos = []
    for dpi in ctx.attr.dpi:
        sos = []
        for gfile in dpi[DefaultInfo].files.to_list():
            if gfile.path.endswith(".so"):
                sos.append(gfile)
        if len(sos) != 1:
            fail("Expected to find exactly one .so for verilog_dv_library dpi argument '", dpi, "'. Found .so: ", sos)
        all_sos.extend(sos)

    out = ctx.outputs.out
    ctx.actions.write(
        output = out,
        content = "\n".join(content),
    )

    trans_srcs = get_transitive_srcs(ctx.files.srcs, ctx.attr.deps + ctx.attr.dpi, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs([out], ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    trans_dpi = get_transitive_srcs(all_sos, ctx.attr.deps, VerilogInfo, "transitive_dpi", allow_other_outputs = False)

    all_files = depset(trans_srcs.to_list() + trans_flists.to_list())

    return [
        VerilogInfo(transitive_sources = trans_srcs, transitive_flists = trans_flists, transitive_dpi = trans_dpi),
        DefaultInfo(
            files = all_files,
            runfiles = ctx.runfiles(files = trans_srcs.to_list() + trans_flists.to_list()),
        ),
    ]

verilog_dv_library = rule(
    doc = """A DV Library.
    Creates a generated flist file from a list of source files.
    """,
    implementation = _verilog_dv_library_impl,
    attrs = {
        "srcs": attr.label_list(
            allow_files = True,
            mandatory = True,
            doc = "Systemverilog source files.\n" +
                  "Files are assumed to be \\`included inside another file (e.g. the package file) and will not be placed on directly in the flist unless declared in the 'in_flist' attribute.",
        ),
        "deps": attr.label_list(
            doc = "verilog_dv_library targets that this target is dependent on.",
        ),
        "in_flist": attr.label_list(
            allow_files = True,
            doc = "Files to be placed directly in the generated flist.\n" +
                  "Best practice recommends 'pkg' and 'interface' files be declared here.\n" +
                  "If this attribute is empty (default), all srcs will put into the flist instead.",
        ),
        "dpi": attr.label_list(
            doc = "cc_libraries to link in through the DPI. Currently, cc_import is not supported for precompiled shared libraries.",
        ),
        "incdir": attr.bool(
            default = True,
            doc = "Generate a +incdir in generated flist for every file's directory declared in 'srcs' attribute.",
        ),
    },
    outputs = {"out": "%{name}.f"},
)

def _verilog_dv_tb_impl(ctx):
    defines = {}
    defines.update(ctx.attr.defines)
    defines.update(gather_shell_defines(ctx.attr.shells))

    top = "tb_top"
    vcs_extra_compile_args = []
    xrun_extra_compile_args = []
    pldm_ice_extra_compile_args = []
    if len(ctx.attr.verilog_config):
        top = ctx.attr.verilog_config.keys()[0]
        cfg = ctx.attr.verilog_config[top]
        vcs_extra_compile_args.append(cfg)
        xrun_extra_compile_args.append("-compcnfg {}".format(cfg))
    vcs_extra_compile_args.append("-top {}".format(top))
    xrun_extra_compile_args.append("-top {}".format(top))
    vcs_extra_compile_args.extend(ctx.attr.extra_compile_args_vcs)
    xrun_extra_compile_args.extend(ctx.attr.extra_compile_args)
    pldm_ice_extra_compile_args.extend(ctx.attr.extra_compile_args)

    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_vcs,
        output = ctx.outputs.compile_args_vcs,
        substitutions = {
            "{COMPILE_ARGS}": ctx.expand_location("\n".join(vcs_extra_compile_args), targets = ctx.attr.extra_runfiles),
            "{DEFINES}": "\n".join(["+define+{}{}".format(key, value) for key, value in defines.items()]),
            #"{DPI_LIBS}": flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_dpi", "-sv_lib", "", "vcs"),
            "{FLISTS}": flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", "\n-f"),
        },
    )
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_xrun,
        output = ctx.outputs.compile_args_xrun,
        substitutions = {
            "{COMPILE_ARGS}": ctx.expand_location("\n".join(xrun_extra_compile_args), targets = ctx.attr.extra_runfiles),
            "{DEFINES}": "\n".join(["-define {}{}".format(key, value) for key, value in defines.items()]),
            "{FLISTS}": flists_to_arguments(ctx.attr.deps + ctx.attr.shells, VerilogInfo, "transitive_flists", "\n-f"),
        },
    )
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_pldm_ice,
        output = ctx.outputs.compile_args_pldm_ice,
        substitutions = {
            "{COMPILE_ARGS}": ctx.expand_location("\n".join(pldm_ice_extra_compile_args), targets = ctx.attr.extra_runfiles),
            "{DEFINES}": "\n".join(["+define+{}{}".format(key, value) for key, value in defines.items()]),
            "{FLISTS}": flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", "\n-f"),
        },
    )
    ctx.actions.expand_template(
        #template = ctx.file._runtime_args_template,
        template = ctx.file._default_sim_opts_xrun,
        output = ctx.outputs.runtime_args_xrun,
        substitutions = {
            "{RUNTIME_ARGS}": ctx.expand_location("\n".join(ctx.attr.extra_runtime_args), targets = ctx.attr.extra_runfiles),
            "{DPI_LIBS}": flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_dpi", "-sv_lib"),
        },
    )
    ctx.actions.expand_template(
        #template = ctx.file._runtime_args_template,
        template = ctx.file._default_sim_opts_vcs,
        output = ctx.outputs.runtime_args_vcs,
        substitutions = {
            "{RUNTIME_ARGS}": ctx.expand_location("\n".join(ctx.attr.extra_runtime_args_vcs), targets = ctx.attr.extra_runfiles),
            "{DPI_LIBS}": flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_dpi", "-sv_lib", "", "vcs"),
        },
    )
    ctx.actions.write(
        output = ctx.outputs.compile_warning_waivers,
        content = "[\n" + "\n".join(["re.compile('{}'),".format(ww) for ww in ctx.attr.warning_waivers]) + "\n]\n",
    )

    # Null action to trigger run?
    ctx.actions.run_shell(
        command = "echo \"Build compile tree directory in \"`pwd`; touch {}".format(ctx.outputs.executable.path),
        outputs = [ctx.outputs.executable],
    )

    trans_srcs = get_transitive_srcs([], ctx.attr.deps + ctx.attr.shells, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs([], ctx.attr.deps + ctx.attr.shells, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    out_deps = depset([
        ctx.outputs.compile_args_vcs,
        ctx.outputs.compile_args_xrun,
        ctx.outputs.compile_args_pldm_ice,
        ctx.outputs.runtime_args_xrun,
        ctx.outputs.runtime_args_vcs,
        ctx.outputs.compile_warning_waivers,
        ctx.outputs.executable
    ])
    all_files = depset([], transitive = [trans_srcs, trans_flists, out_deps])

    return [
        DefaultInfo(
            files = all_files,
            runfiles = ctx.runfiles(files =
                trans_srcs.to_list() +
                trans_flists.to_list() +
                out_deps.to_list() +
                ctx.files.ccf +
                ctx.files.extra_runfiles +
                [ctx.file._default_sim_opts_xrun] +
                [ctx.file._default_sim_opts_vcs]
            ),
        ),
        DVTBInfo(
            ccf = ctx.files.ccf,
        ),
    ]

verilog_dv_tb = rule(
    doc = """A DV Testbench.
    rules_verilog uses two separate rules to strongly differentiate between
    compilation and simulation. verilog_dv_tb is used for compilation and
    verilog_dv_test_cfg is used for simulation.

    A verilog_dv_tb describes how to compile a testbench. It is not a
    standalone executable bazel rule. It is intended to provide simmer (a
    higher level simulation spawning tool) hooks to execute the compile and
    subsequent simulations.
    """,
    implementation = _verilog_dv_tb_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "A list of verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on.\n" +
                  "Dependency ordering within this label list is not necessary if dependencies are consistently declared in all other rules.",
        ),
        "defines": attr.string_dict(
            doc = "Additional preprocessor defines to throw for this testbench compile.\n" +
                  "Key, value pairs are joined without additional characters. If it is a unary flag, set the value portion to be the empty string.\n" +
                  "For binary flags, add an '=' as a suffix to the key.",
        ),
        "warning_waivers": attr.string_list(
            doc = "Waive warnings in the compile. By default, simmer promotes all compile warnings to errors.\n" +
                  "This list is converted to python regular expressions which are imported by simmer to waive warning.\n" +
                  "All warnings may be waived by using '\\*W'\n",
        ),
        "shells": attr.label_list(
            doc = "List of shells to use. Each label must be a verilog_rtl_shell instance.\n" +
                  "Each shell thrown will create two defines:\n" +
                  " \\`define gumi_{module} {module}_shell\n" +
                  " \\`define gumi_use_{module}_shell\n" +
                  "The shell module declaration must be guarded by the gumi_use_{module}_shell define:\n" +
                  " \\`ifdef gumi_use_{module}_shell\n" +
                  "    module {module}_shell(/*AUTOARGS*/);\n" +
                  "      ...\n" +
                  "    endmodule\n" +
                  " \\`endif\n",
        ),
        "ccf": attr.label_list(
            allow_files = True,
            doc = "Coverage configuration file to provider to simmer.",
        ),
        "extra_compile_args": attr.string_list(
            doc = "Additional flags to pass to the xrun compiler.",
        ),
        "extra_compile_args_vcs": attr.string_list(
            doc = "Additional flags to pass to the vcs compiler.",
        ),
        "extra_runtime_args": attr.string_list(
            doc = "Additional flags to throw to xrun simulation run. These flags will not be provided to the compilation, but will be passed to subsequent simulation invocations.",
        ),
        "extra_runtime_args_vcs": attr.string_list(
            doc = "Additional flags to throw to vcs simulation run. These flags will not be provided to the compilation, but will be passed to subsequent simulation invocations.",
        ),
        "extra_runfiles": attr.label_list(
            allow_files = True,
            doc = "Additional files that need to be passed as runfiles to bazel. Most commonly used for files referred to by extra_compile_args or extra_runtime_args.",
        ),
        "verilog_config": attr.string_dict(
            doc = "Key/value pair where the key represents the name of the config object,\n" +
                  "and the value represents a relative pointer to the config .v file.",
        ),
        "_default_sim_opts_xrun": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//vendors/cadence:verilog_dv_default_sim_opts.f",
            doc = "Default XRUN simulation options.",
        ),
        "_default_sim_opts_vcs": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//vendors/synopsys:verilog_dv_default_sim_opts.f",
            doc = "Default VCS simulation options.",
        ),
        "_compile_args_template_xrun": attr.label(
            default = Label("@rules_verilog//vendors/cadence:verilog_dv_tb_compile_args.f.template"),
            allow_single_file = True,
            doc = "Template to generate compilation arguments flist.",
        ),
        "_compile_args_template_vcs": attr.label(
            default = Label("@rules_verilog//vendors/synopsys:verilog_dv_tb_compile_args.f.template"),
            allow_single_file = True,
            doc = "Template to generate compilation arguments flist.",
        ),
        "_compile_args_template_pldm_ice": attr.label(
            default = Label("@rules_verilog//vendors/cadence:verilog_dv_tb_compile_args_pldm_ice.f.template"),
            allow_single_file = True,
            doc = "Template to generate compilation arguments flist.",
        ),
        "_runtime_args_template": attr.label(
            default = Label("@rules_verilog//vendors/common:verilog_dv_tb_runtime_args.f.template"),
            allow_single_file = True,
            doc = "Template to generate runtime args form the 'extra_runtime_args' attribute.",
        ),
    },
    outputs = {
        "runtime_args_xrun": "%{name}_runtime_args_xrun.f",
        "runtime_args_vcs": "%{name}_runtime_args_vcs.f",
        "compile_args_vcs": "%{name}_compile_args_vcs.f",
        "compile_args_xrun": "%{name}_compile_args_xrun.f",
        "compile_args_pldm_ice": "%{name}_compile_args_pldm_ice.f",
        "compile_warning_waivers": "%{name}_compile_warning_waivers",
    },
    # TODO does this still need to be executable with a empty command?
    executable = True,
)

def _verilog_dv_unit_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_flists")
    flists_list = flists.to_list()

    ctx.actions.expand_template(
        template = ctx.file.ut_sim_template,
        output = ctx.outputs.out,
        substitutions = {
            "{SIMULATOR_COMMAND}": ctx.attr._command_override[ToolEncapsulationInfo].command,
            "{DEFAULT_SIM_OPTS}": "-f {}".format(ctx.file.default_sim_opts.short_path),
            "{DPI_LIBS}": flists_to_arguments(ctx.attr.deps, VerilogInfo, "transitive_dpi", "-sv_lib"),
            "{FLISTS}": " ".join(["-f {}".format(f.short_path) for f in flists_list]),
            "{SIM_ARGS}": " ".join(ctx.attr.sim_args),
        },
        is_executable = True,
    )

    runfiles = ctx.runfiles(files = flists_list + srcs_list + [ctx.file.default_sim_opts])
    return [DefaultInfo(
        runfiles = runfiles,
        executable = ctx.outputs.out,
    )]

verilog_dv_unit_test = rule(
    # TODO this could just be a specific use case of verilog_test
    doc = """Compiles and runs a small unit test for DV.

    This is typically a unit test for a single verilog_dv_library and its dependencies.
    Additional sim options may be passed after '--' in the bazel command.
    Interactive example:
      bazel run //hw/dv/interfaces/apb_pkg:test -- -gui
    For ci testing purposes:
      bazel test //hw/dv/interfaces/apb_pkg:test
    """,
    implementation = _verilog_dv_unit_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on.\n" +
                  "Dependency ordering within this label list is not necessary if dependencies are consistently declared in all other rules.",
        ),
        "ut_sim_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_dv_unit_test.sh.template"),
            doc = "The template to generate the bash script to run the simulation.",
        ),
        "default_sim_opts": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//vendors/cadence:verilog_dv_unit_test_opts.f",
            doc = "Default simulator options to pass to the simulator.",
            # TODO remove this and just make it part of the template?
        ),
        "sim_args": attr.string_list(
            doc = "Additional arguments to pass on command line to the simulator.\n" +
                  "Both compile and runtime arguments are allowed because dv_unit_test runs as a single step flow.",
        ),
        "_command_override": attr.label(
            default = Label("@rules_verilog//:verilog_dv_unit_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles.\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:verilog_dv_unit_test_command="runmod -t xrun --"',
        ),
    },
    outputs = {"out": "%{name}_run.sh"},
    test = True,
)

def _verilog_dv_test_cfg_info_aspect_impl(target, ctx):
    # buildifier: disable=print
    print("verilog_dv_test_cfg_info({}, {}, {})".format(target.label, target[DVTestInfo].tb.label, target[DVTestInfo].tags))

    # buildifier: enable=print
    return []

verilog_dv_test_cfg_info_aspect = aspect(
    doc = """Gather information about the tb and tags related to a verilog_dv_test_config for use in simmer.""",
    implementation = _verilog_dv_test_cfg_info_aspect_impl,
    attr_aspects = ["deps", "tags"],
)

def _verilog_dv_tb_ccf_aspect_impl(target, ctx):
    # buildifier: disable=print
    print("verilog_dv_tb_ccf({})".format([f.path for f in target[DVTBInfo].ccf]))

    # buildifier: enable=print
    return []

verilog_dv_tb_ccf_aspect = aspect(
    doc = """Find test to find ccf file mappings simmer.""",
    implementation = _verilog_dv_tb_ccf_aspect_impl,
    attr_aspects = ["ccf"],
)
