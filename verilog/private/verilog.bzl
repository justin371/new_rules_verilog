# vim: set ft=bzl :
"""Generic functions for gathering verilog files."""

CUSTOM_SHELL = "custom"

_SHELLS_DOC = """List of verilog_rtl_shell Labels.
For each Label, a gumi define will be placed on the command line to use this shell instead of the original module.
This requires that the original module was instantiated using \\`gumi_<module_name> instead of just <module_name>."""

VerilogInfo = provider("Transitive Verilog build inputs.", fields = {
    "transitive_sources": "All source files needed by a target. They are retained for compile input tracking and simulator runfiles.",
    "transitive_flists": "All flists which specify ordering of transitive sources.",
    "transitive_vcs_flists": "VCS-compatible flists. Source ordering and per-target filelist boundaries are preserved while Xcelium-only makelib markers are omitted.",
    "transitive_dpi": "Shared libraries (.so/.dll/.dylib) to link in via the DPI for testbenches.",
    "last_module": "This is a convenience accessor. The last module specified is assumed be the top module in a design. This is frequently needed by downstream tools.",
})

ShellInfo = provider("Metadata for a Verilog shell target.", fields = {
    "is_pkg": "Indicates if this verilog_rtl_library used the verilog_rtl_pkg rule. Additional restrictions are imposed on packages to encourage a clean dependency tree.",
    "is_shell_of": "If non-empty, indicates this verilog_rtl_library represents a shell of another module",
    "gumi_path": "The bazel short_path to a gumi file. Used when generating a verilog_rtl_library's associated flist.",
})

ToolEncapsulationInfo = provider("A configurable tool command.", fields = {
    "command": "The command invocation for a particular tool. Useful for aliases, redirection, and wrappers.",
})

def _toolencapsulation_impl(ctx):
    return ToolEncapsulationInfo(command = ctx.build_setting_value)

verilog_tool_encapsulation = rule(
    implementation = _toolencapsulation_impl,
    build_setting = config.string(flag = True),
)

def resolve_unit_test_simulator(explicit_simulator, configured_simulator):
    """Resolve a one-step unit-test simulator, preserving explicit rule values.

    Args:
      explicit_simulator: Optional simulator set directly on the rule.
      configured_simulator: Build-setting target providing the configured default.

    Returns:
      The validated XRUN or VCS simulator name.
    """
    simulator = explicit_simulator or configured_simulator[ToolEncapsulationInfo].command
    if simulator not in ["XRUN", "VCS"]:
        fail("unit-test simulator must be one of ['XRUN', 'VCS'], got '{}'".format(simulator))
    return simulator

_XRUN_ONLY_UNIT_TEST_FLAGS = [
    "-ALLOWREDEFINITION",
    "-sv",
]

_XRUN_ONLY_UNIT_TEST_VALUE_FLAGS = [
    "-access",
    "-debug_opts",
    "-input",
]

def normalize_vcs_unit_test_compile_args(args):
    """Translate legacy Xcelium one-step compile arguments for VCS.

    Existing consumers commonly attach Xcelium defines and debug controls to
    generic unit-test argument attributes. A VCS-configured default must not
    forward those controls to vcs as source-file operands or unknown options.
    """
    result = []
    pending_flag = None
    for arg in args:
        stripped = arg.strip()

        if pending_flag == "-define":
            if not stripped:
                fail("-define in VCS unit-test arguments requires a non-empty value")
            result.append("+define+{}".format(stripped))
            pending_flag = None
            continue
        if pending_flag:
            pending_flag = None
            continue

        if stripped == "-define":
            pending_flag = stripped
            continue
        if stripped.startswith("-define "):
            result.append("+define+{}".format(stripped[len("-define "):].strip()))
            continue

        if stripped in _XRUN_ONLY_UNIT_TEST_FLAGS:
            continue

        consumed_xrun_value = False
        for flag in _XRUN_ONLY_UNIT_TEST_VALUE_FLAGS:
            if stripped == flag:
                pending_flag = flag
                consumed_xrun_value = True
                break
            if stripped.startswith(flag + " ") or stripped.startswith(flag + "="):
                consumed_xrun_value = True
                break
        if consumed_xrun_value:
            continue

        result.append(arg)

    if pending_flag:
        fail("{} in VCS unit-test arguments requires a value".format(pending_flag))

    return result

def gather_shell_defines(shells):
    defines = {}
    for shell in shells:
        if ShellInfo not in shell:
            fail("Not a shell: {}".format(shell))
        if not shell[ShellInfo].is_shell_of:
            fail("Not a shell: {}".format(shell))
        if shell[ShellInfo].is_shell_of == CUSTOM_SHELL:
            # Don't create a shell define for this shell because it has custom setup
            # Usually used when control over per instance shells is desired
            continue

        # implied from label name. this could be more explicit
        defines["gumi_" + shell[ShellInfo].is_shell_of] = "={}".format(shell.label.name)
        defines["gumi_use_{}".format(shell.label.name)] = ""
    return defines

def get_transitive_srcs(srcs, deps, provider, attr_name, allow_other_outputs = False, fallback_attr_name = None):
    """Obtain the source files for a target and its transitive dependencies.

    Args:
      srcs: a list of source files
      deps: a list of targets that are direct dependencies

    Returns:
      a collection of the transitive sources
    """
    trans = []
    for dep in deps:
        if provider in dep:
            if hasattr(dep[provider], attr_name):
                trans.append(getattr(dep[provider], attr_name))
            elif fallback_attr_name and hasattr(dep[provider], fallback_attr_name):
                trans.append(getattr(dep[provider], fallback_attr_name))
            else:
                fail("{} does not provide the required '{}' field".format(dep.label, attr_name))
        elif allow_other_outputs:
            trans.append(dep[DefaultInfo].files)
        else:
            fail("{} does not provide the required provider".format(dep.label))

    return depset(
        srcs,
        transitive = trans,
    )

def runfiles_relative_short_path(f):
    short_path = f.short_path
    if short_path.startswith("../"):
        return "external/" + short_path[3:]
    return short_path

def merge_default_runfiles(ctx, files, targets, transitive_files = None):
    """Create runfiles and merge the default runfiles of dependency targets.

    Args:
      ctx: Rule context.
      files: Direct runtime files.
      targets: Targets whose default runfiles are required.
      transitive_files: Optional depset of additional runtime files.

    Returns:
      A runfiles object containing direct, transitive, and target runfiles.
    """
    return ctx.runfiles(
        files = files,
        transitive_files = transitive_files,
    ).merge_all([target[DefaultInfo].default_runfiles for target in targets])

def verilog_input_inventory_records(deps, extra_files, flist_field = "transitive_flists", fallback_field = None):
    """Return stable inventory entries paired with their source files.

    Returns:
      A sorted list of (inventory entry, File) tuples.
    """
    records = {}
    sources = get_transitive_srcs([], deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    flists = get_transitive_srcs(
        [],
        deps,
        VerilogInfo,
        flist_field,
        allow_other_outputs = False,
        fallback_attr_name = fallback_field,
    )
    for source in sources.to_list():
        records["source\t{}".format(runfiles_relative_short_path(source))] = source
    for flist in flists.to_list():
        records["filelist\t{}".format(runfiles_relative_short_path(flist))] = flist
    for extra_file in extra_files:
        records["runfile\t{}".format(runfiles_relative_short_path(extra_file))] = extra_file
    return [(entry, records[entry]) for entry in sorted(records)]

def verilog_input_inventory(deps, extra_files, flist_field = "transitive_flists", fallback_field = None):
    """Return a stable inventory of Verilog compile inputs.

    Args:
      deps: Targets that provide Verilog inputs.
      extra_files: Additional compile input files.

    Returns:
      A newline-delimited compile input inventory.
    """
    records = verilog_input_inventory_records(deps, extra_files, flist_field, fallback_field)
    return "\n".join([entry for entry, _ in records]) + "\n"

def flists_to_arguments(deps, provider, field, prefix, separator = "", tool_name = None, path_prefix = "", fallback_field = None):
    # Emit Bazel short_path entries so generated filelists stay rooted at the
    # runfiles tree, e.g. hw/... and external/..., instead of machine-specific
    # absolute paths or fragile ../ relative traversals.
    transitive = []
    for dep in deps:
        if provider in dep:
            if hasattr(dep[provider], field):
                transitive.append(getattr(dep[provider], field))
            elif fallback_field and hasattr(dep[provider], fallback_field):
                transitive.append(getattr(dep[provider], fallback_field))
            else:
                fail("{} does not provide the required '{}' field".format(dep.label, field))

        # else:
        #     trans.extend(dep[DefaultInfo].files.to_list())

    trans = depset(transitive = transitive).to_list()

    if tool_name == "vcs":
        formatted_args = []
        for flist in trans:
            normalized_short_path = runfiles_relative_short_path(flist)
            if normalized_short_path.endswith(".so"):
                formatted_args.append(" {} {}{}".format(prefix, path_prefix, normalized_short_path[:-3]))
            else:
                formatted_args.append(" {} {}{}".format(prefix, path_prefix, normalized_short_path))
    else:
        formatted_args = [" {} {}{}".format(prefix, path_prefix, runfiles_relative_short_path(flist)) for flist in trans]

    return separator.join(formatted_args)

def _verilog_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists")
    flists_list = flists.to_list()

    content = ["#!/usr/bin/env bash"]
    tool_executable = None

    if ctx.attr.tool:
        tool_executable = ctx.attr.tool[DefaultInfo].files_to_run.executable
        content.append(tool_executable.short_path)

    flists_args = ["-f {}".format(f.short_path) for f in flists_list]
    content += ctx.attr.pre_flist_args

    for key, value in gather_shell_defines(ctx.attr.shells).items():
        content.append("  +define+{}{}".format(key, value))

    content += flists_args
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            content.append(dep[VerilogInfo].last_module.short_path)
    content += ctx.attr.post_flist_args

    content = ctx.expand_location("\n".join([content[0], " ".join(content[1:])]) + "\n", targets = ctx.attr.data)

    ctx.actions.write(
        output = ctx.outputs.out,
        content = content,
        is_executable = True,
    )

    runfile_targets = ctx.attr.shells + ctx.attr.deps + ctx.attr.data
    runfile_files = flists_list + srcs_list + ctx.files.data
    if ctx.attr.tool:
        runfile_targets.append(ctx.attr.tool)
        runfile_files.append(tool_executable)

    runfiles = merge_default_runfiles(
        ctx,
        files = runfile_files,
        targets = runfile_targets,
    )

    return [DefaultInfo(
        runfiles = runfiles,
        executable = ctx.outputs.out,
    )]

verilog_test = rule(
    doc = """Provides a way to run a test against a set of libs.""",
    implementation = _verilog_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "pre_flist_args": attr.string_list(doc = "Commands and arguments before flist arguments"),
        "post_flist_args": attr.string_list(doc = "Commands and arguments after flist arguments"),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "data": attr.label_list(
            allow_files = True,
            doc = "Non-verilog dependencies",
        ),
        "tool": attr.label(
            cfg = "target",
            executable = True,
            doc = "Label to a single executable tool to run. Inserted before pre_flist_args if set. Do not duplicate in pre_flist_args",
        ),
    },
    outputs = {"out": "%{name}_run.sh"},
    test = True,
)
