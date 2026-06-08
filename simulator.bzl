# vim: set ft=bzl :
# -*- mode: python -*-
"""Compatibility entry point for simulator repository setup rules.

This allows Bazel to precompile DPI code to be able to pass shared
objects to the simulator. Simulator-specific implementations live under
//simulators.

Example usage in another WORKSPACE file:

load("@rules_verilog//:simulator.bzl", "xcelium_setup")
xcelium_setup(name="xcelium")
"""

load("//simulators:vcs.bzl", _vcs_setup = "vcs_setup")
load("//simulators:xrun.bzl", _xcelium_setup = "xcelium_setup")

vcs_setup = _vcs_setup
xcelium_setup = _xcelium_setup
