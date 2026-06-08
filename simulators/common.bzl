# vim: set ft=bzl :
"""Common helpers for simulator repository setup rules."""

VARS = ["PROJ_DIR", "MODULEPATH"]

def dpi_headers_build(headers):
    return """
filegroup(
    name = "dpi_headers",
    srcs = {headers},
    visibility = ["//visibility:public"],
)
""".format(headers = headers)
