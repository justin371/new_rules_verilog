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
        requirement("jinja2"),
    ],
)

py_library(
    name = "vcs",
    srcs = ["vcs.py"],
    deps = [
        ":base",
        # Add deps needed by vcs.py
    ],
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
