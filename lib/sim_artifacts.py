"""Helpers for portable simulator-generated files."""

import os
from pathlib import Path


def runfiles_path(path, runfiles_root):
    """Return a path rooted at the per-test bazel_runfiles_main symlink."""
    absolute_path = os.path.abspath(path)
    absolute_root = os.path.abspath(runfiles_root)
    relative = os.path.relpath(absolute_path, absolute_root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return path
    return os.path.join("bazel_runfiles_main", relative).replace(os.sep, "/")


def write_executable_script(path, content):
    """Write a UTF-8 script and make it executable."""
    path = Path(path)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def materialize_python_script(source_path, destination_path):
    """Copy an importable Python tool into a standalone generated job."""
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    write_executable_script(destination_path, source_path.read_text(encoding="utf-8"))
    return str(destination_path)
