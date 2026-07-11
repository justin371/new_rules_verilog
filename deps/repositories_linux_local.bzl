# vim: set ft=bzl :
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")

def rules_verilog_linux_local_repositories():
    """Legacy Linux-local mirror layout kept separate from public fetch config."""
    maybe(
        http_archive,
        name = "rules_python",
        strip_prefix = "rules_python-0.40.0",
        sha256 = "690e0141724abb568267e003c7b6d9a54925df40c275a870a4d934161dc9dd53",
        urls = ["file:///nfs/dv/shared/dv_repos/rules_python/rules_python-0.40.0.tar.gz"],
    )

    maybe(
        http_archive,
        name = "bazel_skylib",
        sha256 = "bc283cdfcd526a52c3201279cda4bc298652efa898b10b4db0837dc51652756f",
        urls = ["file:///nfs/dv/shared/dv_repos/bazel_skylib/bazel-skylib-1.7.1.tar.gz"],
    )

    maybe(
        http_archive,
        name = "buildifier_prebuilt",
        strip_prefix = "buildifier-prebuilt-6.4.0",
        sha256 = "8ada9d88e51ebf5a1fdff37d75ed41d51f5e677cdbeafb0a22dda54747d6e07e",
        urls = ["file:///nfs/dv/shared/dv_repos/buildifier-prebuilt/6.4.0.tar.gz"],
    )
