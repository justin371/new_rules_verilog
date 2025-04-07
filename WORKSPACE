workspace(name = "rules_verilog")

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")

# https://github.com/bazelbuild/rules_python
maybe(
    name = "rules_python",
    repo_rule = http_archive,
    strip_prefix = "rules_python-0.40.0",
    sha256 = "690e0141724abb568267e003c7b6d9a54925df40c275a870a4d934161dc9dd53",
    url = "file:///nfs/dv/shared/dv_repos/rules_python/rules_python-0.40.0.tar.gz",
)

load("@rules_python//python:repositories.bzl", "py_repositories")
py_repositories()

# buildifier is written in Go and hence needs rules_go to be built.
# See https://github.com/bazelbuild/rules_go for the up to date setup instructions.
maybe(
    name = "io_bazel_rules_go",
    repo_rule = http_archive,
    sha256 = "d6ab6b57e48c09523e93050f13698f708428cfd5e619252e369d377af6597707",
    url = "file:///nfs/dv/shared/dv_repos/rules_go/rules_go-v0.43.0.zip",
)
load("@io_bazel_rules_go//go:deps.bzl", "go_local_sdk", "go_register_toolchains", "go_rules_dependencies")

## The Go programming language
## https://github.com/golang/go
GO_SDK_VERSION = "1.19.1"
go_local_sdk(
    name = "go_sdk",
    path = "//nfs/dv/shared/dv_repos/go/go_{}.linux-amd64".format(GO_SDK_VERSION),
)

go_rules_dependencies()

go_register_toolchains()

# Common useful functions and rules for Bazel
# https://github.com/bazelbuild/bazel-skylib
maybe(
    name = "bazel_skylib",
    repo_rule = http_archive,
    sha256 = "bc283cdfcd526a52c3201279cda4bc298652efa898b10b4db0837dc51652756f",
    url = "file:///nfs/dv/shared/dv_repos/bazel_skylib/bazel-skylib-1.7.1.tar.gz",
)
load("@bazel_skylib//:workspace.bzl", "bazel_skylib_workspace")

bazel_skylib_workspace()

# Gazelle is a build file generator for Bazel projects. It can create new BUILD.bazel files for a project that follows language conventions, and it can update existing build files to include new sources, dependencies, and options.
# Gazelle natively supports Go and protobuf, and it may be extended to support new languages and custom rule sets.
# https://github.com/bazelbuild/bazel-gazelle
http_archive(
    name = "bazel_gazelle",
    sha256 = "b7387f72efb59f876e4daae42f1d3912d0d45563eac7cb23d1de0b094ab588cf",
    url = "file:///nfs/dv/shared/dv_repos/bazel_gazelle/bazel-gazelle-v0.34.0.tar.gz",
)

load("@bazel_gazelle//:deps.bzl", "gazelle_dependencies")

gazelle_dependencies()

# https://github.com/bazelbuild/stardoc
maybe(
    name = "io_bazel_stardoc",
    repo_rule = http_archive,
    sha256 = "0e1ed4a98f26e718776bd64d053d02bb34d98572ccd03d6ba355112a1205706b",
    url = "file:///nfs/dv/shared/dv_repos/stardoc/stardoc-0.7.2.tar.gz",
)

load("@io_bazel_stardoc//:setup.bzl", "stardoc_repositories")

stardoc_repositories()

# Protocol Buffers - Google's data interchange format
# https://github.com/protocolbuffers/protobuf
maybe(
    name = "com_google_protobuf",
    repo_rule = http_archive,
    sha256 = "ba0650be1b169d24908eeddbe6107f011d8df0da5b1a5a4449a913b10e578faf",
    strip_prefix = "protobuf-3.19.4",
    url = "file:///nfs/dv/shared/dv_repos/com_google_protobuf/protobuf-all-3.19.4.tar.gz",
)
load("@com_google_protobuf//:protobuf_deps.bzl", "protobuf_deps")

protobuf_deps()

# https://github.com/bazelbuild/buildtools
maybe(
    name = "com_github_bazelbuild_buildtools",
    repo_rule = http_archive,
    strip_prefix = "buildtools-6.4.0",
    sha256 = "05c3c3602d25aeda1e9dbc91d3b66e624c1f9fdadf273e5480b489e744ca7269",
    urls = ["file:///nfs/dv/shared/dv_repos/buildtools/v6.4.0.tar.gz"],
)

# A bazel toolchain for using prebuilt binaries for buildifier and buildozer
# https://github.com/keith/buildifier-prebuilt
maybe(
    name = "buildifier_prebuilt",
    repo_rule = http_archive,
    sha256 = "8ada9d88e51ebf5a1fdff37d75ed41d51f5e677cdbeafb0a22dda54747d6e07e",
    strip_prefix = "buildifier-prebuilt-6.4.0",
    url = "file:///nfs/dv/shared/dv_repos/buildifier-prebuilt/6.4.0.tar.gz",
)

## Java rules for Bazel
## https://github.com/bazelbuild/rules_java
#maybe(
#    name = "rules_java",
#    repo_rule = http_archive,
#    sha256 = "8afd053dd2a7b85a4f033584f30a7f1666c5492c56c76e04eec4428bdb2a86cf",
#    url = "file:///nfs/dv/shared/dv_repos/rules_java/rules_java-8.5.1.tar.gz",
#)
#
#load("@rules_java//java:rules_java_deps.bzl", "rules_java_dependencies")
#rules_java_dependencies()

