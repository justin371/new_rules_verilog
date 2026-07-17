"""Focused fixtures for public Starlark API contract tests."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")

def _fake_dpi_impl(ctx):
    shared_library = ctx.actions.declare_file(ctx.label.name + ".so")
    ctx.actions.write(shared_library, "")
    return [DefaultInfo(
        files = depset([shared_library]),
        runfiles = ctx.runfiles(files = [ctx.file.runtime_data]),
    )]

fake_dpi = rule(
    implementation = _fake_dpi_impl,
    attrs = {
        "runtime_data": attr.label(
            allow_single_file = True,
            mandatory = True,
        ),
    },
)

def _concrete_requires_tb_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, "requires tb directly or through inherits")
    return analysistest.end(env)

concrete_requires_tb_test = analysistest.make(
    _concrete_requires_tb_test_impl,
    expect_failure = True,
)

def _has_basename(files, basename):
    return any([file.basename == basename for file in files])

def _gumi_override_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    files = target[DefaultInfo].files.to_list()
    runfiles = target[DefaultInfo].default_runfiles.files.to_list()
    asserts.true(env, _has_basename(files, "custom_gumi.vh"), "gumi override is not a transitive source")
    asserts.true(env, _has_basename(runfiles, "custom_gumi.vh"), "gumi override is not a runfile")
    return analysistest.end(env)

gumi_override_test = analysistest.make(_gumi_override_test_impl)

def _dpi_runfiles_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    runfiles = target[DefaultInfo].default_runfiles.files.to_list()
    asserts.true(env, _has_basename(runfiles, "dpi_runtime.data"), "DPI target default runfiles were not merged")
    return analysistest.end(env)

dpi_runfiles_test = analysistest.make(_dpi_runfiles_test_impl)

def _runtime_tool_target_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    runfiles = target[DefaultInfo].default_runfiles.files.to_list()
    asserts.true(env, _has_basename(runfiles, "target_config.data"), "runtime tool did not use the target configuration")
    asserts.false(env, _has_basename(runfiles, "exec_config.data"), "runtime tool used the exec configuration")
    return analysistest.end(env)

runtime_tool_target_config_test = analysistest.make(_runtime_tool_target_config_test_impl)

def _target_analyzes_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, len(target[DefaultInfo].files.to_list()) > 0, "target has no default outputs")
    return analysistest.end(env)

target_analyzes_test = analysistest.make(_target_analyzes_test_impl)
