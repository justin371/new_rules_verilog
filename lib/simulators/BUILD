# vim: set ft=bzl :
# lib/simulators/BUILD
load("@pip_deps//:requirements.bzl", "requirement")

package(default_visibility = ["//visibility:public"])

py_library(
    name = "base",
    srcs = ["base.py"],
    deps = [],
)

py_library(
    name = "xcelium",
    srcs = ["xcelium.py"],
    deps = [
        ":base",
        ":options",
        ":xcelium_options",
        "//lib:coverage_data",
        requirement("jinja2"),
    ],
)

py_library(
    name = "vcs",
    srcs = ["vcs.py"],
    deps = [
        ":base",
        ":options",
        ":vcs_options",
        ":vso",
        "//lib:coverage_data",
    ],
)

py_library(
    name = "vso",
    srcs = ["vso.py"],
)

py_library(
    name = "options",
    srcs = ["options.py"],
)

py_library(
    name = "vcs_options",
    srcs = ["vcs_options.py"],
)

py_library(
    name = "xcelium_options",
    srcs = ["xcelium_options.py"],
)

# Add other simulators here (e.g., questa)

# A convenience target grouping all simulators
py_library(
    name = "simulators",
    deps = [
        ":base",
        ":vcs",
        ":xcelium",
        # Add others
    ],
)
