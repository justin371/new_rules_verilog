# vim: set ft=bzl :
"""Rules for building DV infrastructure."""

load("//deps:gatesim_modes_list.bzl", "GATESIM_MODES")
load(":simulators/pldm.bzl", "pldm_dv_backend")
load(":simulators/vcs.bzl", "vcs_dv_backend")
load(":simulators/xcelium.bzl", "xcelium_dv_backend", "xcelium_dv_unit_test_impl")
load(":verilog.bzl", "VerilogInfo", "gather_shell_defines", "get_transitive_srcs", "merge_default_runfiles", "runfiles_relative_short_path", "verilog_input_inventory")

DVTestInfo = provider("Runtime configuration for a DV test.", fields = {
    "sim_opts": "Simulation :options to carry forward.",
    "uvm_testname": "UVM Test Name; passed to simulator via plusarg +UVM_TESTNAME.",
    "tb": "The verilog_dv_tb (verilog compile) associated with this test. Must be a Label of type verilog_dv_tb.",
    "simulator": "Simulator selected for this test configuration.",
    "tags": "Additional tags to be able to filter in simmer.",
    "timeout": "Main simulation timeout in minutes, excluding socket and pre-run setup.",
    "pre_run": "Bazel run command that can be executed immediately before dv_tb simulation.",
    "description": "Test scenario descriptions.",
})

DVTBInfo = provider("Simulator configuration for a DV testbench.", fields = {
    "ccf": "Coverage config file.",
    "dut_instance": "DUT hierarchy used by coverage reports.",
    "dut_top": "DUT module used to scope code coverage.",
    "run_fail_patterns": "Project-specific simulation failure regexes.",
    "run_pass_patterns": "Project-specific simulation pass regexes.",
    "simulator": "Simulator selected for this DV testbench.",
    "vcs_cm_hier": "VCS coverage hierarchy configuration file.",
    "xcelium_covfile": "Xcelium coverage configuration file.",
})

def _dv_backend(simulator):
    if simulator == "VCS":
        return vcs_dv_backend
    if simulator == "XRUN":
        return xcelium_dv_backend
    fail("simulator must be one of ['XRUN', 'VCS'], got '{}'".format(simulator))

def _build_test_runtime_options(simulator, uvm_testname, sim_opts, timeout, sockets, tags, pre_run, run_pass_patterns, run_fail_patterns):
    timeout_minutes = None
    if timeout != None and timeout >= 0:
        timeout_minutes = timeout
    return {
        "schema_version": 1,
        "simulator": simulator,
        "uvm_testname": uvm_testname,
        "sim_opts": sim_opts,
        "timeout_minutes": timeout_minutes,
        # Keep the legacy key for older simmer readers.
        "timeout": timeout_minutes,
        "sockets": sockets,
        "tags": tags,
        "pre_run": pre_run if pre_run else "",
        "run_pass_patterns": run_pass_patterns,
        "run_fail_patterns": run_fail_patterns,
    }

def _validate_runtime_args(runtime_args, simulator):
    path_arg_prefixes = ["-sv_lib ", "-f ", "-y "]
    sim_root_relative_prefixes = [
        "../",
        "./",
        "external/",
        "hw/",
        "odie/",
        "testbench/",
        "tests/",
    ]
    for arg in runtime_args:
        for prefix in path_arg_prefixes:
            if not arg.startswith(prefix):
                continue
            path_value = arg[len(prefix):]
            for rel_prefix in sim_root_relative_prefixes:
                if path_value.startswith(rel_prefix):
                    fail(
                        "{} runtime arg '{}' uses a sim-root-relative path. " +
                        "Use bazel_runfiles_main/... or an absolute path instead."
                            .format(simulator, arg),
                    )

def _verilog_dv_test_cfg_impl(ctx):
    parent_uvm_testnames = [dep[DVTestInfo].uvm_testname for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "uvm_testname")]
    parent_tbs = [dep[DVTestInfo].tb for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "tb")]
    parent_simulators = [dep[DVTestInfo].simulator for dep in reversed(ctx.attr.inherits) if hasattr(dep[DVTestInfo], "simulator")]
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
    if ctx.attr.timeout >= 0:
        timeout = ctx.attr.timeout
    elif len(parent_timeouts):
        timeout = parent_timeouts[0]

    tb = None
    if ctx.attr.tb:
        tb = ctx.attr.tb
    elif len(parent_tbs):
        tb = parent_tbs[0]
    else:
        fail("verilog_dv_test_cfg {} requires tb directly or through inherits".format(ctx.label))

    tb_simulator = None
    run_pass_patterns = []
    run_fail_patterns = []
    if tb and DVTBInfo in tb:
        tb_simulator = tb[DVTBInfo].simulator
        run_pass_patterns = tb[DVTBInfo].run_pass_patterns
        run_fail_patterns = tb[DVTBInfo].run_fail_patterns

    simulator = None
    if ctx.attr.simulator:
        simulator = ctx.attr.simulator
    elif len(parent_simulators):
        simulator = parent_simulators[0]
    elif tb_simulator:
        simulator = tb_simulator
    else:
        simulator = "XRUN"

    if simulator not in ["XRUN", "VCS"]:
        fail("simulator must be one of ['XRUN', 'VCS'], got '{}'".format(simulator))
    if tb_simulator and simulator != tb_simulator:
        fail(
            "verilog_dv_test_cfg {} resolved simulator '{}' but tb {} uses '{}'."
                .format(ctx.label, simulator, tb.label, tb_simulator),
        )

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
    provider_args["simulator"] = simulator
    provider_args["timeout"] = timeout
    provider_args["sim_opts"] = sim_opts
    provider_args["tags"] = ctx.attr.tags
    provider_args["pre_run"] = pre_run
    provider_args["description"] = description

    socket_name_start = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
    socket_name_chars = socket_name_start + "0123456789"
    for socket_name, socket_command in ctx.attr.sockets.items():
        if not socket_name or socket_name[0] not in socket_name_start or any([char not in socket_name_chars for char in socket_name.elems()]):
            fail("socket name {} must match [A-Za-z_][A-Za-z0-9_]*".format(socket_name))
        if "{socket_file}" not in socket_command:
            fail("socket {} did not have {{socket_file}} in socket_command".format(socket_name))

    dynamic_args = _build_test_runtime_options(
        simulator = simulator,
        uvm_testname = uvm_testname,
        sim_opts = sim_opts,
        timeout = timeout,
        sockets = ctx.attr.sockets,
        tags = ctx.attr.tags,
        pre_run = pre_run,
        run_pass_patterns = run_pass_patterns,
        run_fail_patterns = run_fail_patterns,
    )
    out = ctx.outputs.dynamic_args
    ctx.actions.write(
        output = out,
        content = str(dynamic_args),
    )
    return [DVTestInfo(**provider_args)]

_verilog_dv_test_cfg_rule = rule(
    doc = """A DV test configuration.

    This is not a executable target. It generates multiple files which may then
    be used by simmer (the wrapping tool to invoke the simulator).

    The resolved simulator for the test configuration must match the simulator
    selected by the associated verilog_dv_tb.
    """,
    implementation = _verilog_dv_test_cfg_impl,
    attrs = {
        "abstract": attr.bool(
            default = False,
            doc = "When True, this configuration is abstract and does not represent a complete configuration.\n" +
                  "It is not intended to be executed. It is only intended to be used as a base for other test configurations to inherit from.\n" +
                  "See 'inherits' attribute.\n",
        ),
        "inherits": attr.label_list(
            providers = [DVTestInfo],
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
            providers = [DVTBInfo],
            doc = "The testbench to run this test on. This label must be a 'verilog_dv_tb' target." +
                  "This attribute is inheritable. See 'inherits' attribute.\n" +
                  "Future: Allow tb to be a list of labels to allow a test to run on multiple verilog_dv_tb",
        ),
        "simulator": attr.string(
            default = "",
            doc = "Simulator to use for this test configuration. Supported values are XRUN and VCS.\n" +
                  "This attribute is inheritable. If unspecified across the inheritance chain, XRUN is used unless the associated tb already fixes the simulator.\n" +
                  "The resolved simulator must match the associated verilog_dv_tb.\n",
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
                  "The socket name must match [A-Za-z_][A-Za-z0-9_]* and is passed as \"+SOCKET__<socket_name>=<socket_file>\" to the simulator.\n" +
                  "The socket_file is a short, unique path under /tmp created by simmer to stay within Unix-domain socket path limits.\n" +
                  "The socket_command is a bash command that must contain the literal placeholder \"{socket_file}\"; other shell braces are preserved.\n" +
                  "The socket_command will be run from the root of the project tree.",
        ),
        "pre_run": attr.string(
            doc = "Simmer has the ability to execute a user-specified bazel run command before starting the RTL simulation process.\n" +
                  "This attribute is where the user can define that bazel run command, on a per-test basis.\n" +
                  "For example, if the use wants to run 'bazel run //foo:bar' before their simulation, set this attribute to '//foo:bar'.",
        ),
        "timeout": attr.int(
            default = -1,
            doc = "Main simulation timeout in minutes, excluding socket and pre-run setup.\n" +
                  "This option is inheritable. Use -1 to inherit, 0 to disable, or a positive value to set a timeout.",
        ),
        "description": attr.string(
            doc = "The test scenario descriptions",
        ),
    },
    outputs = {
        "dynamic_args": "%{name}_dynamic_args.py",
    },
)

def _gatesim_target(label, corner):
    value = str(label)
    if ":" in value:
        return value + "_" + corner
    target = value.rsplit("/", 1)[-1]
    return "{}:{}_{}".format(value, target, corner)

def verilog_dv_test_cfg(name = None, tags = None, abstract = None, inherits = None, uvm_testname = None, tb = None, simulator = None, sim_opts = None, no_run = None, sockets = None, pre_run = None, timeout = None, description = None, gls_tb = None, pre_opts = None, post_opts = None, gatesim_modes = GATESIM_MODES):
    sim_opts = dict(sim_opts) if sim_opts != None else {}
    pre_opts = dict(pre_opts) if pre_opts != None else {}
    post_opts = dict(post_opts) if post_opts != None else {}

    rule_args = {}
    if name != None:
        rule_args["name"] = name
    if abstract != None:
        rule_args["abstract"] = abstract
    if inherits != None:
        rule_args["inherits"] = inherits
    if uvm_testname != None:
        rule_args["uvm_testname"] = uvm_testname
    if tb != None:
        rule_args["tb"] = tb
    if simulator != None:
        rule_args["simulator"] = simulator
    if no_run != None:
        rule_args["no_run"] = no_run
    if sockets != None:
        rule_args["sockets"] = sockets
    if pre_run != None:
        rule_args["pre_run"] = pre_run
    if timeout != None:
        rule_args["timeout"] = timeout
    if description != None:
        rule_args["description"] = description

    pre_sim_opts = dict(sim_opts)
    pre_sim_opts.update(pre_opts)
    rule_args["sim_opts"] = pre_sim_opts

    # The base target represents pre-layout simulation; gatesim expands into
    # separate corner targets below and must not tag the base target itself.
    pre_sim_tags = []
    if tags != None:
        for tag in tags:
            if tag != "gatesim":
                pre_sim_tags.append(tag)

    rule_args["tags"] = pre_sim_tags
    _verilog_dv_test_cfg_rule(**rule_args)

    if tags != None and "gatesim" in tags:
        post_sim_opts = dict(sim_opts)
        post_sim_opts.update(post_opts)
        rule_args["sim_opts"] = post_sim_opts

        # Schedule tags stay on the base target so each generated timing corner
        # does not independently enter the same CI cadence.
        post_sim_tags = []
        for tag in tags:
            if tag != "ci_gate" and tag != "nightly" and tag != "weekly":
                post_sim_tags.append(tag)
        rule_args["tags"] = post_sim_tags

        # Each corner rewrites all generated-label relationships consistently.
        for corner in gatesim_modes:
            rule_args["name"] = name + "_" + corner
            if inherits != None:
                rule_args["inherits"] = [_gatesim_target(inherit, corner) for inherit in inherits]

            if gls_tb != None:
                rule_args["tb"] = _gatesim_target(gls_tb, corner)
            elif tb != None:
                rule_args["tb"] = _gatesim_target(tb, corner)
            if uvm_testname != None:
                rule_args["uvm_testname"] = uvm_testname
            _verilog_dv_test_cfg_rule(**rule_args)

def _is_dpi_shared_lib(path):
    return path.endswith(".so") or path.endswith(".dll") or path.endswith(".dylib")

def _dv_library_source_lines(directories, in_flist):
    content = []
    for directory in directories:
        content.append("+incdir+{}".format(directory if directory else "."))
    content.extend([runfiles_relative_short_path(f) for f in in_flist])
    return content

def _verilog_dv_library_impl(ctx):
    if ctx.attr.incdir:
        # Using dirname may result in bazel-out included in path
        directories = depset([runfiles_relative_short_path(f)[:-len(f.basename) - 1] for f in ctx.files.srcs]).to_list()
    else:
        directories = []

    # # Add output files from direct dependencies (from genrules)
    srcs = depset(ctx.files.srcs, transitive = [dep[DefaultInfo].files for dep in ctx.attr.deps if VerilogInfo not in dep])

    if len(ctx.files.in_flist):
        in_flist = ctx.files.in_flist
    else:
        in_flist = ctx.files.srcs

    source_lines = _dv_library_source_lines(directories, in_flist)

    all_sos = []
    for dpi in ctx.attr.dpi:
        sos = []
        for gfile in dpi[DefaultInfo].files.to_list():
            if _is_dpi_shared_lib(gfile.path):
                sos.append(gfile)
        if len(sos) != 1:
            fail("Expected to find exactly one shared library (.so/.dll/.dylib) for verilog_dv_library dpi argument '", dpi, "'. Found: ", sos)
        all_sos.extend(sos)

    out = xcelium_dv_backend.materialize_library_flist(ctx, source_lines)
    vcs_out = vcs_dv_backend.materialize_library_flist(ctx, source_lines, out)

    trans_srcs = get_transitive_srcs(ctx.files.srcs, ctx.attr.deps + ctx.attr.dpi, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs([out], ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    trans_vcs_flists = get_transitive_srcs(
        [vcs_out],
        ctx.attr.deps,
        VerilogInfo,
        "transitive_vcs_flists",
        allow_other_outputs = False,
        fallback_attr_name = "transitive_flists",
    )
    trans_dpi = get_transitive_srcs(all_sos, ctx.attr.deps, VerilogInfo, "transitive_dpi", allow_other_outputs = False)

    all_files = depset(transitive = [trans_srcs, trans_flists, trans_vcs_flists])

    return [
        VerilogInfo(
            transitive_sources = trans_srcs,
            transitive_flists = trans_flists,
            transitive_vcs_flists = trans_vcs_flists,
            transitive_dpi = trans_dpi,
        ),
        DefaultInfo(
            files = all_files,
            runfiles = ctx.runfiles(transitive_files = all_files),
        ),
    ]

verilog_dv_library = rule(
    doc = """A DV Library.
    Creates a generated flist file from a list of source files.

    Generated paths use Bazel short_path form so the flist is rooted at the
    runfiles tree (for example hw/... and external/...). Hand-authored nested
    filelists should prefer the same style and avoid ../ upward traversals.

    Recommended DPI usage is to keep SystemVerilog files in srcs/in_flist and
    provide shared libraries through the dpi attribute, for example:

      cc_binary(
          name = "dpi",
          srcs = glob(["*.c"]),
          linkshared = True,
      )

      verilog_dv_library(
          name = "pkg",
          srcs = glob(["*.sv"]),
          dpi = [":dpi"],
      )
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
            doc = "cc_libraries to link in through the DPI. Currently, cc_import is not supported for precompiled shared libraries.\n" +
                  "Prefer placing shared libraries here rather than globbing .so files into srcs.\n" +
                  "Example:\n" +
                  "  cc_library(name = \"dpi\", srcs = glob([\"*.c\"]))\n" +
                  "  verilog_dv_library(name = \"pkg\", srcs = glob([\"*.sv\"]), dpi = [\":dpi\"])",
        ),
        "incdir": attr.bool(
            default = True,
            doc = "Generate a +incdir in generated flist for every file's directory declared in 'srcs' attribute.",
        ),
        "makelib": attr.string(
            default = "",
            doc = ("Compile this target into the named Xcelium library through -makelib/-endlib. " +
                   "VCS receives the same ordered sources through a separate -file boundary; VCS recompilation isolation is provided by -Mupdate and Partition Compile rather than Xcelium library syntax."),
        ),
    },
    outputs = {"out": "%{name}.f"},
)

def _verilog_dv_tb_impl(ctx):
    simulator = ctx.attr.simulator
    backend = _dv_backend(simulator)
    if len(ctx.files.ccf) > 1:
        fail("verilog_dv_tb {} accepts only one ccf file".format(ctx.label))
    if ctx.file.xcelium_covfile and ctx.files.ccf:
        fail("verilog_dv_tb {} accepts either xcelium_covfile or legacy ccf, not both".format(ctx.label))
    has_msie_primary = len(ctx.attr.msie_primary_deps) > 0
    has_msie_incremental = len(ctx.attr.msie_incremental_deps) > 0
    if has_msie_primary != has_msie_incremental:
        fail("verilog_dv_tb {} must configure both msie_primary_deps and msie_incremental_deps".format(ctx.label))
    has_msie_extras = (
        ctx.attr.msie_primary_extra_compile_args or
        ctx.attr.msie_incremental_extra_compile_args or
        ctx.attr.msie_primary_extra_runfiles or
        ctx.attr.msie_incremental_extra_runfiles
    )
    backend.validate_tb(ctx, has_msie_primary, has_msie_extras)

    xcelium_covfile = ctx.file.xcelium_covfile
    if not xcelium_covfile and ctx.files.ccf:
        xcelium_covfile = ctx.files.ccf[0]

    defines = {}
    defines.update(ctx.attr.defines)
    defines.update(gather_shell_defines(ctx.attr.shells))

    top = "tb_top"
    compile_args = []
    if len(ctx.attr.verilog_config):
        if len(ctx.attr.verilog_config) > 1:
            fail("verilog_dv_tb {} accepts only one verilog_config entry".format(ctx.label))
        top = ctx.attr.verilog_config.keys()[0]
        cfg = ctx.attr.verilog_config[top]
        compile_args.append(backend.config_arg(cfg))

    #vcs_extra_compile_args.append("-top {}".format(top))
    #xrun_extra_compile_args.append("-top {}".format(top))
    #vcs_extra_compile_args.append("-top hdl_top -top hvl_top")
    #xrun_extra_compile_args.append("-top hdl_top -top hvl_top")
    selected_compile_args = ctx.attr.extra_compile_args
    compile_args.extend(selected_compile_args)

    compile_config = backend.compile_config(ctx, defines, compile_args)

    ctx.actions.expand_template(
        template = compile_config.template,
        output = ctx.outputs.compile_args,
        substitutions = {
            "{COMPILE_ARGS}": ctx.expand_location("\n".join(compile_config.args), targets = ctx.attr.extra_runfiles),
            "{DEFINES}": compile_config.defines,
            "{FLISTS}": compile_config.flists,
        },
    )

    # These legacy implicit outputs are declared for every simulator value.
    pldm_dv_backend.materialize_declared_outputs(ctx, defines, selected_compile_args)
    extra_compile_outputs = backend.extra_compile_outputs(ctx, defines, selected_compile_args, compile_config)

    runtime_config = backend.runtime_config(ctx)
    runtime_args = [ctx.expand_location(arg, targets = ctx.attr.extra_runfiles) for arg in ctx.attr.extra_runtime_args]
    _validate_runtime_args(runtime_args, simulator)

    ctx.actions.expand_template(
        template = runtime_config.template,
        output = ctx.outputs.runtime_args,
        substitutions = {
            "{RUNTIME_ARGS}": "\n".join(runtime_args),
            "{DPI_LIBS}": runtime_config.dpi,
        },
    )
    ctx.actions.write(
        output = ctx.outputs.compile_warning_waivers,
        content = "[\n" + "\n".join(["re.compile({}),".format(repr(ww)) for ww in ctx.attr.warning_waivers]) + "\n]\n",
    )
    all_deps = ctx.attr.deps + ctx.attr.shells + ctx.attr.msie_primary_deps + ctx.attr.msie_incremental_deps
    compile_input_files = (
        ctx.files.ccf +
        ctx.files.extra_runfiles +
        ctx.files.msie_primary_extra_runfiles +
        ctx.files.msie_incremental_extra_runfiles +
        ([ctx.file.xcelium_covfile] if ctx.file.xcelium_covfile else []) +
        ([ctx.file.vcs_cm_hier] if ctx.file.vcs_cm_hier else [])
    )
    ctx.actions.write(
        output = ctx.outputs.compile_inputs,
        content = verilog_input_inventory(
            all_deps,
            compile_input_files,
            flist_field = compile_config.flist_field,
            fallback_field = compile_config.fallback_flist_field,
        ),
    )
    tb_options = {
        "compile_inputs": runfiles_relative_short_path(ctx.outputs.compile_inputs),
        "dut_instance": ctx.attr.dut_instance,
        "dut_top": ctx.attr.dut_top,
    }
    tb_options.update(backend.tb_options(ctx, extra_compile_outputs, xcelium_covfile))
    ctx.actions.write(
        output = ctx.outputs.tb_options,
        content = str(tb_options),
    )

    ctx.actions.write(
        output = ctx.outputs.executable,
        content = "",
        is_executable = True,
    )

    trans_srcs = get_transitive_srcs([], all_deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs(
        [],
        all_deps,
        VerilogInfo,
        compile_config.flist_field,
        allow_other_outputs = False,
        fallback_attr_name = compile_config.fallback_flist_field,
    )
    generated_outputs = [
        ctx.outputs.compile_args,
        ctx.outputs.compile_inputs,
        ctx.outputs.runtime_args,
        ctx.outputs.compile_warning_waivers,
        ctx.outputs.tb_options,
        ctx.outputs.executable,
    ]
    generated_outputs.extend(extra_compile_outputs.generated_outputs)
    out_deps = depset(generated_outputs)
    all_files = depset([], transitive = [trans_srcs, trans_flists, out_deps])
    runfile_targets = (
        all_deps +
        ctx.attr.ccf +
        ctx.attr.extra_runfiles +
        ctx.attr.msie_primary_extra_runfiles +
        ctx.attr.msie_incremental_extra_runfiles
    )
    if ctx.attr.xcelium_covfile:
        runfile_targets.append(ctx.attr.xcelium_covfile)
    if ctx.attr.vcs_cm_hier:
        runfile_targets.append(ctx.attr.vcs_cm_hier)

    return [
        DefaultInfo(
            files = all_files,
            runfiles = merge_default_runfiles(
                ctx,
                files = ctx.files.ccf + ctx.files.extra_runfiles + ctx.files.msie_primary_extra_runfiles + ctx.files.msie_incremental_extra_runfiles + ([ctx.file.xcelium_covfile] if ctx.file.xcelium_covfile else []) + ([ctx.file.vcs_cm_hier] if ctx.file.vcs_cm_hier else []) + [runtime_config.template],
                targets = runfile_targets,
                transitive_files = all_files,
            ),
        ),
        DVTBInfo(
            ccf = ctx.files.ccf,
            dut_instance = ctx.attr.dut_instance,
            dut_top = ctx.attr.dut_top,
            run_fail_patterns = ctx.attr.run_fail_patterns,
            run_pass_patterns = ctx.attr.run_pass_patterns,
            simulator = simulator,
            vcs_cm_hier = ctx.file.vcs_cm_hier,
            xcelium_covfile = xcelium_covfile,
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

    The compile and runtime filelists are generated according to the selected
    simulator. The generated file names are <name>_compile_args.f and
    <name>_runtime_args.f.
    """,
    implementation = _verilog_dv_tb_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "A list of verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on.\n" +
                  "Dependency ordering within this label list is not necessary if dependencies are consistently declared in all other rules.",
        ),
        "msie_primary_deps": attr.label_list(
            doc = "Xcelium MSIE dependencies for the stable primary DUT/netlist partition. Configure together with msie_incremental_deps.",
        ),
        "msie_incremental_deps": attr.label_list(
            doc = "Xcelium MSIE dependencies for the changing testbench/test partition. Configure together with msie_primary_deps.",
        ),
        "msie_primary_extra_compile_args": attr.string_list(
            doc = "Xcelium compile/elaboration flags used only while building the MSIE primary snapshot.",
        ),
        "msie_incremental_extra_compile_args": attr.string_list(
            doc = "Xcelium compile/elaboration flags used only while building the MSIE incremental snapshot.",
        ),
        "msie_primary_extra_runfiles": attr.label_list(
            allow_files = True,
            doc = "Files referenced only by msie_primary_extra_compile_args, such as primary SDF command files.",
        ),
        "msie_incremental_extra_runfiles": attr.label_list(
            allow_files = True,
            doc = "Files referenced only by msie_incremental_extra_compile_args.",
        ),
        "defines": attr.string_dict(
            doc = "Additional preprocessor defines to throw for this testbench compile.\n" +
                  "Key, value pairs are joined without additional characters. If it is a unary flag, set the value portion to be the empty string.\n" +
                  "For binary flags, add an '=' as a suffix to the key.",
        ),
        "dut_instance": attr.string(
            default = "hdl_top.dut",
            doc = "DUT instance hierarchy used by coverage reports.",
        ),
        "dut_top": attr.string(
            default = "dut",
            doc = "DUT module name used to scope code coverage.",
        ),
        "simulator": attr.string(
            default = "XRUN",
            doc = "Simulator to use for this DV testbench. Supported values are XRUN and VCS.\n" +
                  "The selected simulator determines the contents of the generated compile/runtime filelists.\n",
        ),
        "warning_waivers": attr.string_list(
            doc = "Waive warnings in the compile. By default, simmer promotes all compile warnings to errors.\n" +
                  "This list is converted to python regular expressions which are imported by simmer to waive warning.\n" +
                  "Xcelium waivers commonly match '\\*W,<ID>'; VCS waivers commonly match 'Warning-\\[<ID>\\]'.\n",
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
            doc = "Coverage configuration file to provide to simmer.",
        ),
        "xcelium_covfile": attr.label(
            allow_single_file = True,
            doc = "Xcelium coverage configuration file. Replaces the legacy ccf attribute.",
        ),
        "vcs_cm_hier": attr.label(
            allow_single_file = True,
            doc = "VCS -cm_hier coverage configuration file.",
        ),
        "extra_compile_args": attr.string_list(
            doc = "Additional flags to pass to the selected simulator compile/elaboration step.\n",
        ),
        "extra_runtime_args": attr.string_list(
            doc = "Additional flags to pass to selected simulator runs. These flags will not be provided to compilation.\n" +
                  "Simulation runs execute from the per-test sim directory, so path-bearing arguments should generally use absolute paths or bazel_runfiles_main/... paths.\n",
        ),
        "extra_runfiles": attr.label_list(
            allow_files = True,
            doc = "Additional files that need to be passed as runfiles to bazel. Most commonly used for files referred to by extra_compile_args or extra_runtime_args.\n" +
                  "Prefer passing labels here and referencing their runfiles-root-relative paths from generated filelists.",
        ),
        "run_pass_patterns": attr.string_list(
            doc = "Regexes that identify a successful simulation. When set, at least one must match.",
        ),
        "run_fail_patterns": attr.string_list(
            doc = "Additional regexes that identify a failed simulation.",
        ),
        "verilog_config": attr.string_dict(
            doc = "Key/value pair where the key represents the name of the config object,\n" +
                  "and the value represents a relative pointer to the config .v file.",
        ),
        "_default_sim_opts_xrun": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//vendors/cadence:verilog_dv_default_sim_opts.f",
            doc = "Default Xcelium simulation options.",
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
        "_compile_args_template_pldm_sa": attr.label(
            default = Label("@rules_verilog//vendors/cadence:verilog_dv_tb_compile_args_pldm_sa.f.template"),
            allow_single_file = True,
            doc = "Template to generate compilation arguments flist.",
        ),
    },
    outputs = {
        "runtime_args": "%{name}_runtime_args.f",
        "compile_args": "%{name}_compile_args.f",
        "compile_inputs": "%{name}_compile_inputs.txt",
        "compile_args_pldm_ice": "%{name}_compile_args_pldm_ice.f",
        "compile_args_pldm_sa": "%{name}_compile_args_pldm_sa.f",
        "compile_warning_waivers": "%{name}_compile_warning_waivers",
        "tb_options": "%{name}_tb_options.py",
    },
    # TODO does this still need to be executable with a empty command?
    executable = True,
)

verilog_dv_unit_test = rule(
    doc = """Compiles and runs a small unit test for DV.

    This is typically a unit test for a single verilog_dv_library and its dependencies.
    Additional sim options may be passed after '--' in the bazel command.
    Interactive example:
      bazel run //hw/dv/interfaces/apb_pkg:test -- -gui
    For ci testing purposes:
      bazel test //hw/dv/interfaces/apb_pkg:test
    """,
    implementation = xcelium_dv_unit_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on.\n" +
                  "Dependency ordering within this label list is not necessary if dependencies are consistently declared in all other rules.",
        ),
        "simulator": attr.string(
            default = "XRUN",
            values = ["XRUN", "VCS"],
            doc = "Simulator to use for this one-step unit test. Only XRUN is supported; VCS uses verilog_dv_tb + simmer.\n",
        ),
        "ut_sim_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_dv_unit_test.sh.template"),
            doc = "The template to generate the bash script to run the simulation.\n",
        ),
        "default_sim_opts": attr.label(
            allow_single_file = True,
            default = "@rules_verilog//vendors/cadence:verilog_dv_unit_test_opts.f",
            doc = "Default simulator options to pass to the simulator.\n",
            # TODO remove this and just make it part of the template?
        ),
        "sim_args": attr.string_list(
            doc = "Deprecated compile arguments. Use compile_args and run_args instead.",
        ),
        "compile_args": attr.string_list(
            doc = "Additional arguments passed to compilation/elaboration.",
        ),
        "run_args": attr.string_list(
            doc = "Additional arguments passed only to simulation runtime.",
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
    print("verilog_dv_test_cfg_info({}, {}, {}, {})".format(
        target.label,
        target[DVTestInfo].tb.label,
        target[DVTestInfo].tags,
        target[DVTestInfo].simulator,
    ))

    # buildifier: enable=print
    return []

verilog_dv_test_cfg_info_aspect = aspect(
    doc = """Gather information about the tb and tags related to a verilog_dv_test_config for use in simmer.""",
    implementation = _verilog_dv_test_cfg_info_aspect_impl,
)
