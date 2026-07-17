# vim: set ft=bzl :
"""Generic functions for gathering verilog files."""

CUSTOM_SHELL = "custom"

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
    """Return stable inventory entries paired with their source files."""
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
