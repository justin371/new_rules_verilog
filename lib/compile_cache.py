"""Fingerprint simulator builds before allowing --no-compile reuse."""

import hashlib
import json
import os
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


def _extra_inputs_digest(paths):
    digest = hashlib.sha256()
    for path in sorted(os.path.abspath(os.fspath(path)) for path in paths if path):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_bytes(path))
        digest.update(b"\0")
    return digest.hexdigest()


def compile_fingerprint(project_dir,
                        compile_script,
                        compile_args_path,
                        compile_inputs_path=None,
                        runfiles_root=None,
                        extra_input_paths=(),
                        environment=None):
    """Return the source, generated filelist and compile-mode identity."""
    fingerprint = {
        "schema_version": 4,
        "compile_script_sha256": _digest_bytes(compile_script.encode("utf-8")),
        "compile_args_sha256": _digest_bytes(_file_bytes(compile_args_path)),
        "environment": dict(sorted((environment or {}).items())),
    }
    if compile_inputs_path:
        fingerprint["compile_inputs_sha256"] = _compile_inputs_digest(compile_inputs_path, runfiles_root)
    if extra_input_paths:
        fingerprint["extra_inputs_sha256"] = _extra_inputs_digest(extra_input_paths)
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
