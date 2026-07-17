# vim: set ft=bzl :
load("@rules_python//python:defs.bzl", "py_binary")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "compile_input_digest",
    srcs = ["compile_input_digest.py"],
    python_version = "PY3",
)

exports_files([
    "rtl.bzl",
    "dv.bzl",
    "simulators/pldm.bzl",
    "simulators/vcs.bzl",
    "simulators/xcelium.bzl",
    "verilog.bzl",
])
