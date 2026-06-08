#!/usr/bin/env python
"""Normalize nested compile/source flist paths to runfiles-root-relative form.

This tool is intended for hand-authored or environment-generated nested
filelists inside a Bazel runfiles tree, for example:

  bazel_runfiles_main/external/vip_xrun_svt_pcie/pkg.f

It rewrites relative path fragments such as:

  +incdir+../vip_xrun_svt_pcie/include/sverilog
  ../vip_xrun_svt_pcie/include/sverilog/svt_pcie.uvm.pkg

into runfiles-root-relative paths such as:

  +incdir+external/vip_xrun_svt_pcie/include/sverilog
  external/vip_xrun_svt_pcie/include/sverilog/svt_pcie.uvm.pkg

This is intended for nested source/filelist content used during compile/elab,
where the wrappers launch the simulator from ``bazel_runfiles_main``.

Do not blindly apply this to simulation-time runtime-args files. Simulation
runs execute from the per-test sim directory, so runtime path arguments may
need absolute paths or an explicit ``bazel_runfiles_main/`` prefix instead.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PATH_PREFIXES = (
    "+incdir+",
    "-f ",
    "-v ",
    "-y ",
)


def to_posix(path: Path) -> str:
    return path.as_posix()


def find_runfiles_root(flist_path: Path) -> Path:
    current = flist_path.resolve()
    for parent in [current.parent] + list(current.parents):
        if parent.name == "bazel_runfiles_main":
            return parent
    raise ValueError("Could not find enclosing bazel_runfiles_main for '{}'".format(flist_path))


def rewrite_path_token(token: str, flist_dir: Path, runfiles_root: Path) -> str:
    if not token.startswith("../") and not token.startswith("./"):
        return token

    resolved = (flist_dir / token).resolve()
    try:
        relative = resolved.relative_to(runfiles_root)
    except ValueError:
        return token
    return to_posix(relative)


def normalize_line(line: str, flist_dir: Path, runfiles_root: Path) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line

    line_ending = ""
    if line.endswith("\r\n"):
        content = line[:-2]
        line_ending = "\r\n"
    elif line.endswith("\n"):
        content = line[:-1]
        line_ending = "\n"
    else:
        content = line

    for prefix in PATH_PREFIXES:
        if content.startswith(prefix):
            token = content[len(prefix):].strip()
            rewritten = rewrite_path_token(token, flist_dir, runfiles_root)
            return "{}{}{}".format(prefix, rewritten, line_ending)

    leading = content[: len(content) - len(content.lstrip(" "))]
    token = content.strip()
    rewritten = rewrite_path_token(token, flist_dir, runfiles_root)
    if rewritten == token:
        return line
    return "{}{}{}".format(leading, rewritten, line_ending)


def normalize_flist(path: Path) -> bool:
    runfiles_root = find_runfiles_root(path)
    flist_dir = path.resolve().parent
    original = path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated = [normalize_line(line, flist_dir, runfiles_root) for line in original]
    if updated == original:
        return False
    path.write_text("".join(updated), encoding="utf-8")
    return True


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "flists",
        nargs="+",
        help="One or more .f file paths inside a bazel_runfiles_main tree.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    options = parse_args(argv)
    changed = 0
    for flist in options.flists:
        path = Path(flist)
        if not path.exists():
            print("Missing flist: {}".format(path), file=sys.stderr)
            return 1
        try:
            was_changed = normalize_flist(path)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if was_changed:
            changed += 1
            print("Updated {}".format(path))
        else:
            print("No change {}".format(path))
    print("Normalized {} file(s)".format(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
