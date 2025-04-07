"""External dependencies for rules_verilog"""

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def _maybe(repo_rule, name, **kwargs):
    if name not in native.existing_rules():
        repo_rule(name = name, **kwargs)

# Update the SHA and VERSION to the lastest version available here:
# https://github.com/bazelbuild/rules_python/releases.

SHA="84aec9e21cc56fbc7f1335035a71c850d1b9b5cc6ff497306f84cced9a769841"

VERSION="0.23.1"

#def verilog_dependencies():
#    _maybe(
#        repo_rule = http_archive,
#        name = "rules_python",
#        url = "https://github.com/bazelbuild/rules_python/releases/download/{}/rules_python-{}.tar.gz".format(VERSION,VERSION),
#        sha256 = SHA,
#    )

