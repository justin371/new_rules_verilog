# vim: set ft=bzl :
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")

def rules_verilog_public_repositories():
    maybe(
        http_archive,
        name = "rules_python",
        strip_prefix = "rules_python-0.40.0",
        sha256 = "690e0141724abb568267e003c7b6d9a54925df40c275a870a4d934161dc9dd53",
        urls = ["https://github.com/bazelbuild/rules_python/releases/download/0.40.0/rules_python-0.40.0.tar.gz"],
    )

    maybe(
        http_archive,
        name = "io_bazel_rules_go",
        sha256 = "d6ab6b57e48c09523e93050f13698f708428cfd5e619252e369d377af6597707",
        urls = ["https://github.com/bazelbuild/rules_go/releases/download/v0.43.0/rules_go-v0.43.0.zip"],
    )

    maybe(
        http_archive,
        name = "bazel_skylib",
        sha256 = "bc283cdfcd526a52c3201279cda4bc298652efa898b10b4db0837dc51652756f",
        urls = ["https://github.com/bazelbuild/bazel-skylib/releases/download/1.7.1/bazel-skylib-1.7.1.tar.gz"],
    )

    maybe(
        http_archive,
        name = "bazel_gazelle",
        sha256 = "b7387f72efb59f876e4daae42f1d3912d0d45563eac7cb23d1de0b094ab588cf",
        urls = ["https://github.com/bazelbuild/bazel-gazelle/releases/download/v0.34.0/bazel-gazelle-v0.34.0.tar.gz"],
    )

    maybe(
        http_archive,
        name = "rules_java",
        sha256 = "29ba147c583aaf5d211686029842c5278e12aaea86f66bd4a9eb5e525b7f2701",
        urls = [
            "https://mirror.bazel.build/github.com/bazelbuild/rules_java/releases/download/6.3.0/rules_java-6.3.0.tar.gz",
            "https://github.com/bazelbuild/rules_java/releases/download/6.3.0/rules_java-6.3.0.tar.gz",
        ],
    )

    maybe(
        http_archive,
        name = "com_google_protobuf",
        sha256 = "75be42bd736f4df6d702a0e4e4d30de9ee40eac024c4b845d17ae4cc831fe4ae",
        strip_prefix = "protobuf-21.7",
        urls = [
            "https://mirror.bazel.build/github.com/protocolbuffers/protobuf/archive/v21.7.tar.gz",
            "https://github.com/protocolbuffers/protobuf/archive/v21.7.tar.gz",
        ],
    )

    maybe(
        http_archive,
        name = "io_bazel_stardoc",
        # Stardoc 0.6.2 aligns with Bazel 7.x dependency expectations.
        strip_prefix = "stardoc-0.6.2",
        urls = ["https://github.com/bazelbuild/stardoc/archive/refs/tags/0.6.2.tar.gz"],
    )

    maybe(
        http_archive,
        name = "com_github_bazelbuild_buildtools",
        strip_prefix = "buildtools-6.4.0",
        sha256 = "05c3c3602d25aeda1e9dbc91d3b66e624c1f9fdadf273e5480b489e744ca7269",
        urls = ["https://github.com/bazelbuild/buildtools/archive/refs/tags/v6.4.0.tar.gz"],
    )

    maybe(
        http_archive,
        name = "buildifier_prebuilt",
        strip_prefix = "buildifier-prebuilt-6.4.0",
        sha256 = "8ada9d88e51ebf5a1fdff37d75ed41d51f5e677cdbeafb0a22dda54747d6e07e",
        urls = ["https://github.com/keith/buildifier-prebuilt/archive/refs/tags/6.4.0.tar.gz"],
    )
