"""Fingerprint simulator builds before allowing --no-compile reuse."""

import hashlib
import json
import os
import re
import tempfile

FINGERPRINT_FILE = ".compile_fingerprint.json"


class CompileDirectoryLock:
    """Advisory lock held while validating or updating a compile directory."""

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))
        self._filep = None

    def acquire(self, blocking=True):
        if self._filep is not None:
            return True

        import fcntl

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        filep = open(self.path, "a+", encoding="utf-8")
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(filep, operation)
        except BlockingIOError:
            filep.close()
            return False
        except BaseException:
            filep.close()
            raise
        self._filep = filep
        return True

    def release(self):
        if self._filep is None:
            return

        import fcntl

        try:
            fcntl.flock(self._filep, fcntl.LOCK_UN)
        finally:
            self._filep.close()
            self._filep = None


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


def _compile_inputs_manifest_digest(compile_inputs_path):
    digest = hashlib.sha256()
    with open(compile_inputs_path, "r", encoding="utf-8") as filep:
        for line in filep:
            entry = line.rstrip("\n")
            if "\t" not in entry:
                raise RuntimeError("Malformed compile input inventory entry: {!r}".format(entry))
            digest.update(entry.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def _read_compile_inputs_digest(path):
    try:
        with open(path, "r", encoding="ascii") as filep:
            digest = filep.read().strip()
    except OSError as exc:
        raise RuntimeError("Cannot read Bazel compile input digest '{}': {}".format(path, exc)) from exc
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise RuntimeError("Malformed Bazel compile input digest '{}': {!r}".format(path, digest))
    return digest


def _extra_inputs_digest(paths):
    digest = hashlib.sha256()
    for path in sorted(os.path.abspath(os.fspath(path)) for path in paths if path):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_bytes(path))
        digest.update(b"\0")
    return digest.hexdigest()


def _extra_inputs_content_digest(paths):
    file_digests = sorted(_digest_bytes(_file_bytes(path)) for path in paths if path)
    return _digest_bytes(*(digest.encode("ascii") for digest in file_digests))


def normalize_compile_script_paths(compile_script, path_replacements):
    """Replace host-specific absolute paths with stable fingerprint tokens."""
    normalized = compile_script
    replacements = ((os.path.abspath(os.fspath(path)), "<{}>".format(name)) for name, path in path_replacements.items()
                    if path)
    for path, token in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(path, token)
    return normalized


def compile_fingerprint(project_dir,
                        compile_script,
                        compile_args_path,
                        compile_inputs_path=None,
                        runfiles_root=None,
                        compile_inputs_digest_path=None,
                        extra_input_paths=(),
                        environment=None):
    """Return the source, generated filelist and compile-mode identity."""
    fingerprint = {
        "schema_version": 7,
        "compile_script_sha256": _digest_bytes(compile_script.encode("utf-8")),
        "compile_args_sha256": _digest_bytes(_file_bytes(compile_args_path)),
        "environment": dict(sorted((environment or {}).items())),
    }
    if compile_inputs_path:
        fingerprint["compile_inputs_sha256"] = (_read_compile_inputs_digest(compile_inputs_digest_path)
                                                if compile_inputs_digest_path else _compile_inputs_digest(
                                                    compile_inputs_path, runfiles_root))
        fingerprint["compile_inputs_manifest_sha256"] = _compile_inputs_manifest_digest(compile_inputs_path)
    if extra_input_paths:
        fingerprint["extra_inputs_sha256"] = _extra_inputs_digest(extra_input_paths)
        fingerprint["extra_inputs_content_sha256"] = _extra_inputs_content_digest(extra_input_paths)
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


def invalidate_compile_fingerprint(job_dir):
    try:
        os.remove(_fingerprint_path(job_dir))
    except FileNotFoundError:
        pass


def _changed_fingerprint_fields(actual, expected, prefix=""):
    changed = []
    for key in sorted(set(actual) | set(expected)):
        field = "{}.{}".format(prefix, key) if prefix else key
        actual_value = actual.get(key)
        expected_value = expected.get(key)
        if isinstance(actual_value, dict) and isinstance(expected_value, dict):
            changed.extend(_changed_fingerprint_fields(actual_value, expected_value, field))
        elif actual_value != expected_value:
            changed.append(field)
    return changed


def validate_compile_fingerprint(job_dir, expected):
    path = _fingerprint_path(job_dir)
    if not os.path.isfile(path):
        raise RuntimeError("--no-compile requires {}. Recompile this testbench first.".format(path))
    with open(path, "r", encoding="utf-8") as filep:
        actual = json.load(filep)
    if actual != expected:
        changed = ", ".join(_changed_fingerprint_fields(actual, expected))
        raise RuntimeError("Compile build fingerprint mismatch in {} (changed: {}). Recompile this testbench.".format(
            job_dir, changed))


def can_reuse_compile(job_dir, expected, validate_artifacts):
    """Return an automatic cache decision without turning a miss into an error."""
    try:
        validate_artifacts()
        validate_compile_fingerprint(job_dir, expected)
    except (OSError, RuntimeError, ValueError) as exc:
        return False, str(exc)
    return True, None
