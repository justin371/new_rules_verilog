# vim: set ft=bzl :
workspace(name = "rules_verilog")

load("//deps:repositories_public.bzl", "rules_verilog_public_repositories")

# Active dependency source: public GitHub / mirror fetches.
rules_verilog_public_repositories()

# Legacy Linux-local mirror config lives separately in //deps:repositories_linux_local.bzl.
# Swap the load/call above if that environment needs to be restored.

load("@rules_python//python:repositories.bzl", "py_repositories")
py_repositories()

load("@rules_python//python:pip.bzl", "pip_parse")

pip_parse(
    name = "pip_deps",
    requirements_lock = "//:requirements.txt",
)

load("@pip_deps//:requirements.bzl", "install_deps")
install_deps()

load("@io_bazel_rules_go//go:deps.bzl", "go_download_sdk", "go_register_toolchains", "go_rules_dependencies")

## The Go programming language
## https://github.com/golang/go
GO_SDK_VERSION = "1.19.1"
## Linux local SDK path:
## /nfs/dv/shared/dv_repos/go/go_{}.linux-amd64
go_download_sdk(
    name = "go_sdk",
    version = GO_SDK_VERSION,
    register_toolchains = False,
)

go_rules_dependencies()

go_register_toolchains()

load("@bazel_skylib//:workspace.bzl", "bazel_skylib_workspace")

bazel_skylib_workspace()

load("@bazel_gazelle//:deps.bzl", "gazelle_dependencies")

gazelle_dependencies()

load("@io_bazel_stardoc//:setup.bzl", "stardoc_repositories")

stardoc_repositories()

load("@rules_jvm_external//:repositories.bzl", "rules_jvm_external_deps")
load("@io_bazel_stardoc//:deps.bzl", "stardoc_external_deps")

rules_jvm_external_deps()

load("@rules_jvm_external//:setup.bzl", "rules_jvm_external_setup")

rules_jvm_external_setup()
stardoc_external_deps()

load("@stardoc_maven//:defs.bzl", stardoc_pinned_maven_install = "pinned_maven_install")
stardoc_pinned_maven_install()

load("@buildifier_prebuilt//:defs.bzl", "buildifier_prebuilt_register_toolchains")
buildifier_prebuilt_register_toolchains()
