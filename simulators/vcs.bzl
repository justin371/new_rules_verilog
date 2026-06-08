# vim: set ft=bzl :
"""Repository setup for Synopsys VCS."""

load("//simulators:common.bzl", "VARS", "dpi_headers_build")

VCS_DPI_HEADERS = ["svdpi.h", "svdpi_src.h"]

def _vcs_setup_impl(repository_ctx):
    if repository_ctx.attr.name.upper() != "VCS":
        fail("Name vcs_setup rule: 'VCS'!")
    result = repository_ctx.execute(
        ["runmod", "vcs", "--", "printenv", "VCS_HOME"],
        environment = repository_ctx.os.environ,
        # working_directory="..",
    )
    if result.return_code:
        fail("{}\n{}\nFailed running find VCS command".format(result.stdout, result.stderr))
    vcs_home = result.stdout.strip()
    include = "{}/include".format(vcs_home)
    for hdr in VCS_DPI_HEADERS:
        hdr_path = "{}/{}".format(include, hdr)
        repository_ctx.symlink(hdr_path, hdr)
    repository_ctx.file("BUILD", dpi_headers_build(VCS_DPI_HEADERS))

vcs_setup = repository_rule(
    implementation = _vcs_setup_impl,
    local = True,
    environ = VARS,
)
