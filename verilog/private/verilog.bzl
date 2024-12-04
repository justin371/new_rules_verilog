"""Generic functions for gathering verilog files."""

CUSTOM_SHELL = "custom"

_SHELLS_DOC = """List of verilog_rtl_shell Labels.
For each Label, a gumi define will be placed on the command line to use this shell instead of the original module.
This requires that the original module was instantiated using \\`gumi_<module_name> instead of just <module_name>."""

VerilogInfo = provider(fields = {
    "transitive_sources": "All source source files needed by a target. This flow is not currently setup to do partioned compile, so all files need to be carried through to the final step for compilation as a whole.",
    "transitive_flists": "All flists which specify ordering of transitive sources.",
    "transitive_dpi": "Shared libraries (only .so extension allowed) to link in via the DPI for testbenches.",
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

    return depset(
        srcs,
        transitive = trans,
    )

def flists_to_arguments(deps, provider, field, prefix, separator = "", tool_name=None):
    trans = []
    for dep in deps:
        if provider in dep:
            trans.extend(getattr(dep[provider], field).to_list())

        # else:
        #     trans.extend(dep[DefaultInfo].files.to_list())

    #return "".join([" -f {}".format(flist.path) for flist in trans])
    trans_depset = depset(trans)
    trans = trans_depset.to_list()

    if tool_name == "vcs":
        formatted_args = [
            " {} ../{}".format(prefix, flist.short_path[:-3]) if flist.short_path.endswith(".so")
            else " {} {}".format(prefix, flist.short_path)
            for flist in trans
        ]
    else:
        formatted_args = [" {} {}".format(prefix, flist.short_path) for flist in trans]

    #return separator.join([" {} {}".format(prefix, flist.short_path) for flist in trans])
    return separator.join(formatted_args)

def _verilog_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists")
    flists_list = flists.to_list()

    content = []

    if ctx.attr.tool:
        content.append(ctx.attr.tool[DefaultInfo].files_to_run.executable.short_path)

    flists_args = ["-f {}".format(f.short_path) for f in flists_list]
    content += ctx.attr.pre_flist_args

    for key, value in gather_shell_defines(ctx.attr.shells).items():
        content.append("  +define+{}{}".format(key, value))

    content += flists_args
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            content.append(dep[VerilogInfo].last_module.short_path)
    content += ctx.attr.post_flist_args

    content = ctx.expand_location(" ".join(content), targets = ctx.attr.data)

    ctx.actions.write(
        output = ctx.outputs.out,
        content = content,
        is_executable = True,
    )

    if ctx.attr.tool:
        tool_runfiles = ctx.attr.tool[DefaultInfo].data_runfiles.files
    else:
        tool_runfiles = depset([])

    runfiles = ctx.runfiles(files = flists_list + srcs_list + ctx.files.data, transitive_files = tool_runfiles)

    # runfiles = ctx.runfiles(files = flists_list + srcs_list)
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
        "tool": attr.label(doc = "Label to a single tool to run. Inserted at before pre_flist_args if set. Do not duplicate in pre_flist_args"),
    },
    outputs = {"out": "%{name}_run.sh"},
    test = True,
)
