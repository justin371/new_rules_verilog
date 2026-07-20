"""Compatibility fixture for downstream synthesis aspects."""

# buildifier: disable=bzl-visibility
load("@rules_verilog//verilog/private:rtl.bzl", "create_flist_content")

# buildifier: disable=bzl-visibility
load("@rules_verilog//verilog/private:verilog.bzl", "ShellInfo", "VerilogInfo")

SynthFlistInfo = provider(
    "Generated synthesis filelist for compatibility validation.",
    fields = {"flist": "Generated synthesis filelist"},
)

def _synth_aspect_impl(target, ctx):
    if VerilogInfo not in target or not hasattr(ctx.rule.attr, "modules"):
        return []

    synth_flist = ctx.actions.declare_file("synth__{}.f".format(ctx.rule.attr.name))
    content = create_flist_content(
        ctx.rule,
        gumi_path = target[ShellInfo].gumi_path,
        allow_library_discovery = False,
        no_synth = ctx.rule.attr.no_synth,
    )
    ctx.actions.write(
        output = synth_flist,
        content = "\n".join(content),
    )
    return [SynthFlistInfo(flist = synth_flist)]

_synth_aspect = aspect(
    implementation = _synth_aspect_impl,
    attr_aspects = ["deps"],
)

def _synth_flist_set_impl(ctx):
    return [DefaultInfo(files = depset([
        dep[SynthFlistInfo].flist
        for dep in ctx.attr.deps
        if SynthFlistInfo in dep
    ]))]

synth_flist_set = rule(
    implementation = _synth_flist_set_impl,
    attrs = {
        "deps": attr.label_list(aspects = [_synth_aspect]),
    },
)
