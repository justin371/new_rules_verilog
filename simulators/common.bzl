# vim: set ft=bzl :
"""Common helpers for simulator repository setup rules."""

def simulator_environment(repository_ctx):
    return {
        name: repository_ctx.getenv(name, "")
        for name in ["MODULEPATH", "PATH", "PROJ_DIR"]
    }

def dpi_headers_build(headers):
    return """
filegroup(
    name = "dpi_headers",
    srcs = {headers},
    visibility = ["//visibility:public"],
)
""".format(headers = headers)
