"""Helpers for portable simulator-generated files."""

import os
from pathlib import Path
import shutil


def runfiles_path(path, runfiles_root):
    """Return a path rooted at the per-test bazel_runfiles_main symlink."""
    absolute_path = os.path.abspath(path)
    absolute_root = os.path.abspath(runfiles_root)
    relative = os.path.relpath(absolute_path, absolute_root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return path
    return os.path.join("bazel_runfiles_main", relative).replace(os.sep, "/")


def find_bazel_executable(project_dir, name):
    """Find a rules_verilog binary in a main or external Bazel workspace."""
    project_dir = Path(project_dir)
    candidates = [
        project_dir / "bazel-bin/bin" / name,
        project_dir / "bazel-bin/external/rules_verilog/bin" / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which(name)
    if executable:
        return executable
    raise FileNotFoundError("Could not find Bazel executable '{}'; checked {}".format(name, candidates))


def write_executable_script(path, content):
    """Write a UTF-8 script and make it executable."""
    path = Path(path)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
