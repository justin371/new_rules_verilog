# vim: set ft=bzl :
"""Generic functions for gathering verilog files."""

CUSTOM_SHELL = "custom"

VerilogInfo = provider(fields = {
    "transitive_sources": "All source source files needed by a target. This flow is not currently setup to do partioned compile, so all files need to be carried through to the final step for compilation as a whole.",
    "transitive_flists": "All flists which specify ordering of transitive sources.",
    "transitive_dpi": "Shared libraries (.so/.dll/.dylib) to link in via the DPI for testbenches.",
    "last_module": "This is a convenience accessor. The last module specified is assumed be the top module in a design. This is frequently needed by downstream tools.",
})

ShellInfo = provider(fields = {
    "is_pkg": "Indicates if this verilog_rtl_library used the verilog_rtl_pkg rule. Additional restrictions are imposed on packages to encourage a clean dependency tree.",
    "is_shell_of": "If non-empty, indicates this verilog_rtl_library represents a shell of another module",
    "gumi_path": "The bazel short_path to a gumi file. Used when generating a verilog_rtl_library's associated flist.",
})

ToolEncapsulationInfo = provider(fields = {
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

def get_transitive_srcs(srcs, deps, provider, attr_name, allow_other_outputs = False):
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
            trans.append(getattr(dep[provider], attr_name))
        elif allow_other_outputs:
            trans.append(dep[DefaultInfo].files)
        else:
            fail("{} does not provide the required provider".format(dep.label))

    return depset(
        srcs,
        transitive = trans,
    )

def _runfiles_relative_short_path(f):
    short_path = f.short_path
    if short_path.startswith("../"):
        return "external/" + short_path[3:]
    return short_path

def flists_to_arguments(deps, provider, field, prefix, separator = "", tool_name = None, path_prefix = ""):
    # Emit Bazel short_path entries so generated filelists stay rooted at the
    # runfiles tree, e.g. hw/... and external/..., instead of machine-specific
    # absolute paths or fragile ../ relative traversals.
    transitive = []
    for dep in deps:
        if provider in dep:
            transitive.append(getattr(dep[provider], field))

        # else:
        #     trans.extend(dep[DefaultInfo].files.to_list())

    trans = depset(transitive = transitive).to_list()

    if tool_name == "vcs":
        formatted_args = []
        for flist in trans:
            normalized_short_path = _runfiles_relative_short_path(flist)
            if normalized_short_path.endswith(".so"):
                formatted_args.append(" {} {}{}".format(prefix, path_prefix, normalized_short_path[:-3]))
            else:
                formatted_args.append(" {} {}{}".format(prefix, path_prefix, normalized_short_path))
    else:
        formatted_args = [" {} {}{}".format(prefix, path_prefix, _runfiles_relative_short_path(flist)) for flist in trans]

    return separator.join(formatted_args)
