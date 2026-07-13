#!/usr/bin/env bash
set -uo pipefail

if [[ $# -ne 0 ]]; then
  echo "Documentation is maintained directly; doc_test.sh accepts no arguments." >&2
  exit 1
fi

exec python3.12 tests/docs_test.py
