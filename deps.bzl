# vim: set ft=bzl :
"""Public dependency entry point for rules_verilog consumers."""

load("//deps:repositories_public.bzl", "rules_verilog_public_repositories")

def verilog_dependencies():
    """Declare the external repositories required by rules_verilog."""
    rules_verilog_public_repositories()
