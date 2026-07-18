"""Fingerprint simulator builds before allowing --no-compile reuse."""

import hashlib
import json
import os
import re
import shlex
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


def _extra_input_digests(paths):
    path_digest = hashlib.sha256()
    content_digests = []
    for path in sorted(os.path.abspath(os.fspath(path)) for path in paths if path):
        content = _file_bytes(path)
        path_digest.update(path.encode("utf-8"))
        path_digest.update(b"\0")
        path_digest.update(content)
        path_digest.update(b"\0")
        content_digests.append(_digest_bytes(content))
    content_digest = _digest_bytes(*(digest.encode("ascii") for digest in sorted(content_digests)))
    return path_digest.hexdigest(), content_digest


def _directory_inputs(path):
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for filename in sorted(files):
            yield os.path.join(root, filename)


def discover_filelist_inputs(filelist_path, working_directory):
    """Return existing files and include/library directory contents referenced by a simulator filelist."""
    if not filelist_path:
        return []

    working_directory = os.path.abspath(working_directory)
    root_filelist = os.path.abspath(filelist_path)
    discovered = set()
    parsed_filelists = set()
    pending = [(root_filelist, working_directory)]

    def resolve(path, base_directory):
        expanded = os.path.expanduser(os.path.expandvars(path))
        return os.path.abspath(expanded if os.path.isabs(expanded) else os.path.join(base_directory, expanded))

    def add_path(path, base_directory, include_directory=False):
        resolved = resolve(path, base_directory)
        if os.path.isfile(resolved):
            discovered.add(resolved)
        elif include_directory and os.path.isdir(resolved):
            discovered.update(_directory_inputs(resolved))
        return resolved

    while pending:
        current_filelist, relative_base = pending.pop()
        if current_filelist in parsed_filelists:
            continue
        parsed_filelists.add(current_filelist)
        if not os.path.isfile(current_filelist):
            continue
        discovered.add(current_filelist)
        try:
            with open(current_filelist, "r", encoding="utf-8", errors="surrogateescape") as filep:
                tokens = shlex.split(filep.read(), comments=True, posix=True)
        except ValueError:
            continue

        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in ("-f", "-file", "-F") and index + 1 < len(tokens):
                nested_base = os.path.dirname(current_filelist) if token == "-F" else relative_base
                nested = add_path(tokens[index + 1], nested_base)
                pending.append((nested, nested_base))
                index += 2
                continue
            if token.startswith("-file="):
                nested = add_path(token.split("=", 1)[1], relative_base)
                pending.append((nested, relative_base))
                index += 1
                continue
            if token.startswith("+incdir+"):
                for directory in token[len("+incdir+"):].split("+"):
                    if directory:
                        add_path(directory, relative_base, include_directory=True)
                index += 1
                continue
            if token in ("-v", "-y") and index + 1 < len(tokens):
                add_path(tokens[index + 1], relative_base, include_directory=(token == "-y"))
                index += 2
                continue
            if not token.startswith(("-", "+")):
                add_path(token, relative_base)
            index += 1

    return sorted(discovered)


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
        extra_inputs_digest, extra_inputs_content_digest = _extra_input_digests(extra_input_paths)
        fingerprint["extra_inputs_sha256"] = extra_inputs_digest
        fingerprint["extra_inputs_content_sha256"] = extra_inputs_content_digest
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
