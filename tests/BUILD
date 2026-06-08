# vim: set ft=bzl :
load("@com_github_bazelbuild_buildtools//buildifier:def.bzl", "buildifier")

buildifier(
    name = "buildifier_format_diff",
    diff_command = "diff",
    mode = "diff",
)

buildifier(
    name = "buildifier_lint",
    lint_mode = "warn",
    lint_warnings = [
        "-function-docstring-args",
        "-function-docstring",
    ],
    mode = "fix",
)

buildifier(
    name = "buildifier_fix",
    lint_mode = "fix",
    mode = "fix",
)
