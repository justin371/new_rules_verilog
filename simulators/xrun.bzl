# vim: set ft=bzl :
"""Repository setup for Cadence Xcelium/XRUN."""

load("//simulators:common.bzl", "VARS", "dpi_headers_build")

XRUN_DPI_HEADERS = ["svdpi.h", "svdpi_compatibility.h"]

def _xcelium_setup_impl(repository_ctx):
    if repository_ctx.attr.name.upper() != "XCELIUM":
        fail("Name xcelium_setup rule: 'XCELIUM'!")
    result = repository_ctx.execute(
        ["runmod", "xrun", "--", "printenv", "XCELIUMHOME"],
        environment = repository_ctx.os.environ,
        # working_directory="..",
    )
    if result.return_code:
        fail("{}\n{}\nFailed running find XCELIUM command".format(result.stdout, result.stderr))
    xcelium_home = result.stdout.strip()
    include = "{}/tools.lnx86/include".format(xcelium_home)
    for hdr in XRUN_DPI_HEADERS:
        hdr_path = "{}/{}".format(include, hdr)
        repository_ctx.symlink(hdr_path, hdr)
    repository_ctx.file("BUILD", dpi_headers_build(XRUN_DPI_HEADERS))

xcelium_setup = repository_rule(
    implementation = _xcelium_setup_impl,
    local = True,
    environ = VARS,
)
