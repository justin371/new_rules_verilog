# vim: set ft=bzl :
# lib/simulators/BUILD
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
        # Add deps needed by xcelium.py, e.g., from project root if needed
        # "//lib:cmn_logging", # Example if needed, but likely not directly
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
