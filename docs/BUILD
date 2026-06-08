# vim: set ft=bzl :
load("@io_bazel_stardoc//stardoc:stardoc.bzl", "stardoc")
load("@bazel_skylib//:bzl_library.bzl", "bzl_library")

bzl_library(
    name = "defs_rules",
    srcs = [
        "//verilog:defs.bzl",
        "//verilog/private:dv.bzl",
        "//verilog/private:rtl.bzl",
        "//verilog/private:verilog.bzl",
    ],
    deps = ["//deps:gatesim_modes_list"],
)

stardoc(
    name = "defs_docs",
    out = "defs.md",
    input = "//verilog:defs.bzl",
    deps = [":defs_rules"],
)
