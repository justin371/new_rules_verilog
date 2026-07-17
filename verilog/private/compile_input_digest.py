#!/usr/bin/env python3
"""Generate the content digest used by simmer's compile cache."""

import hashlib
import sys


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: compile_input_digest MANIFEST OUTPUT")

    manifest_path, output_path = sys.argv[1:]
    digest = hashlib.sha256()
    with open(manifest_path, "r", encoding="utf-8") as manifest:
        for line in manifest:
            fields = line.rstrip("\n").split("\t", 2)
            if len(fields) != 3:
                raise RuntimeError("Malformed compile input digest entry: {!r}".format(line.rstrip("\n")))
            kind, relative_path, input_path = fields
            digest.update("{}\t{}".format(kind, relative_path).encode("utf-8"))
            digest.update(b"\0")
            with open(input_path, "rb") as input_file:
                for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")

    with open(output_path, "w", encoding="ascii") as output:
        output.write(digest.hexdigest() + "\n")


if __name__ == "__main__":
    main()
