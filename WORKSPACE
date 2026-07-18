# vim: set ft=bzl :
workspace(name = "rules_verilog")

load("//deps:repositories_public.bzl", "rules_verilog_public_repositories")

# Active dependency source: public GitHub / mirror fetches.
rules_verilog_public_repositories()

# Legacy Linux-local mirror config lives separately in //deps:repositories_linux_local.bzl.
# Swap the load/call above if that environment needs to be restored.

load("@rules_python//python:repositories.bzl", "py_repositories")

py_repositories()

load("@bazel_skylib//:workspace.bzl", "bazel_skylib_workspace")

bazel_skylib_workspace()

load("@buildifier_prebuilt//:defs.bzl", "buildifier_prebuilt_register_toolchains")

buildifier_prebuilt_register_toolchains()

local_repository(
    name = "filelist_external_fixture",
    path = "tests/external_fixture",
)

local_repository(
    name = "external_verilog_fixture",
    path = "tests/external_setup_smoke/external_verilog_fixture",
)
