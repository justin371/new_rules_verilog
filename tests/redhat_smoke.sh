#!/usr/bin/env bash
set -Eeuo pipefail

trap 'status=$?; printf "ERROR: redhat_smoke.sh failed at line %s: %s (exit %s)\n" "$LINENO" "$BASH_COMMAND" "$status" >&2; exit "$status"' ERR

if [[ ! -r /etc/os-release ]] || ! grep -Eqi '^(ID|ID_LIKE)=.*(rhel|fedora|centos|rocky|almalinux)' /etc/os-release; then
  echo "ERROR: this smoke test must run on a Red Hat-compatible Linux host." >&2
  exit 1
fi

python3.12 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'

if [[ "$(bazel --version)" != "bazel 7.7.1" ]]; then
  echo "ERROR: bazel 7.7.1 is required; found $(bazel --version)." >&2
  exit 1
fi

bazel test --test_output=errors //:buildifier_test //tests/... //examples/dpi:dpi_c_test
./tests/doc_test.sh
