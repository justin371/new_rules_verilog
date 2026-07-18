#!/usr/bin/env python3
"""Create an offline rules_verilog archive and temporary consumer workspace."""

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile

ARCHIVE_PREFIX = "new_rules_verilog-local"
CONSUMER_FILES = (
    ".bazelrc",
    ".bazelversion",
    "BUILD",
    "rules_verilog_external_setup_smoke_test.py",
    "rules_verilog_external_setup_top.sv",
)


def _repository_files(repository_root):
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return sorted(Path(path.decode("utf-8", errors="surrogateescape")) for path in result.stdout.split(b"\0") if path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    fixture_dir = args.fixture_dir.resolve()
    output_root = args.output_root.resolve()
    consumer_dir = output_root / "http-archive-consumer"
    archive_path = output_root / "rules_verilog-local.tar.gz"
    consumer_dir.mkdir(parents=True)

    with tarfile.open(archive_path, "w:gz") as archive:
        for relative_path in _repository_files(repository_root):
            source_path = repository_root / relative_path
            archive.add(source_path, arcname="{}/{}".format(ARCHIVE_PREFIX, relative_path.as_posix()), recursive=False)

    for filename in CONSUMER_FILES:
        shutil.copy2(fixture_dir / filename, consumer_dir / filename)
    shutil.copytree(fixture_dir / "external_verilog_fixture", consumer_dir / "external_verilog_fixture")

    archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    workspace = (fixture_dir / "WORKSPACE.http_archive.template").read_text(encoding="utf-8")
    workspace = workspace.replace("__RULES_VERILOG_ARCHIVE_SHA256__", archive_sha256)
    workspace = workspace.replace("__RULES_VERILOG_ARCHIVE_URL__", archive_path.as_uri())
    (consumer_dir / "WORKSPACE").write_text(workspace, encoding="utf-8")


if __name__ == "__main__":
    main()
