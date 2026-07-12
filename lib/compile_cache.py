"""Fingerprint simulator builds before allowing --no-compile reuse."""

import hashlib
import json
import os
import subprocess
import tempfile

FINGERPRINT_FILE = ".compile_fingerprint.json"


def _digest_bytes(*values):
    digest = hashlib.sha256()
    for value in values:
        digest.update(value)
        digest.update(b"\0")
    return digest.hexdigest()


def _file_bytes(path):
    try:
        with open(path, "rb") as filep:
            return filep.read()
    except OSError:
        return b"<missing>"


def _git(project_dir, *args):
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        check=False,
        capture_output=True,
    )


def _source_digest(project_dir):
    head = _git(project_dir, "rev-parse", "HEAD")
    diff = _git(project_dir, "diff", "--binary", "--no-ext-diff", "HEAD", "--")
    untracked = _git(project_dir, "ls-files", "--others", "--exclude-standard", "-z")
    if head.returncode or diff.returncode or untracked.returncode:
        return "unavailable"

    digest = hashlib.sha256()
    digest.update(head.stdout)
    digest.update(diff.stdout)
    for relative_path in sorted(filter(None, untracked.stdout.split(b"\0"))):
        digest.update(relative_path)
        digest.update(_file_bytes(os.path.join(project_dir, os.fsdecode(relative_path))))
    return digest.hexdigest()


def _compile_inputs_digest(compile_inputs_path, runfiles_root):
    if not compile_inputs_path:
        return None

    digest = hashlib.sha256()
    with open(compile_inputs_path, "r", encoding="utf-8") as filep:
        for line in filep:
            entry = line.rstrip("\n")
            _, separator, relative_path = entry.partition("\t")
            if not separator:
                raise RuntimeError("Malformed compile input inventory entry: {!r}".format(entry))
            input_path = os.path.join(runfiles_root, relative_path)
            if not os.path.isfile(input_path):
                raise RuntimeError("Compile input inventory references missing file: {}".format(input_path))
            digest.update(entry.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_file_bytes(input_path))
            digest.update(b"\0")
    return digest.hexdigest()


def compile_fingerprint(project_dir, compile_script, compile_args_path, compile_inputs_path=None, runfiles_root=None):
    """Return the source, generated filelist and compile-mode identity."""
    fingerprint = {
        "schema_version": 2,
        "source_sha256": _source_digest(os.fspath(project_dir)),
        "compile_script_sha256": _digest_bytes(compile_script.encode("utf-8")),
        "compile_args_sha256": _digest_bytes(_file_bytes(compile_args_path)),
    }
    if compile_inputs_path:
        fingerprint["compile_inputs_sha256"] = _compile_inputs_digest(compile_inputs_path, runfiles_root)
    return fingerprint


def _fingerprint_path(job_dir):
    return os.path.join(job_dir, FINGERPRINT_FILE)


def write_compile_fingerprint(job_dir, fingerprint):
    os.makedirs(job_dir, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".compile-fingerprint-", dir=job_dir, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
            json.dump(fingerprint, filep, indent=2, sort_keys=True)
            filep.write("\n")
        os.replace(temporary_path, _fingerprint_path(job_dir))
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def validate_compile_fingerprint(job_dir, expected):
    path = _fingerprint_path(job_dir)
    if not os.path.isfile(path):
        raise RuntimeError("--no-compile requires {}. Recompile this testbench first.".format(path))
    with open(path, "r", encoding="utf-8") as filep:
        actual = json.load(filep)
    if actual != expected:
        raise RuntimeError("--no-compile build fingerprint mismatch in {}. Recompile this testbench.".format(job_dir))
