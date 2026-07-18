#!/usr/bin/env bash
set -Eeuo pipefail

trap 'status=$?; printf "ERROR: external_setup_smoke_test.sh failed at line %s: %s (exit %s)\n" "$LINENO" "$BASH_COMMAND" "$status" >&2; exit "$status"' ERR

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
fixture_dir="$repo_root/tests/external_setup_smoke"
temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/rules_verilog_external_setup.XXXXXX")"

cleanup() {
  rm -rf -- "$temporary_root"
}
trap cleanup EXIT

python_path="$(command -v python3.12)"

(
  cd "$fixture_dir"
  if [[ "$(bazel --version)" != "bazel 7.7.1" ]]; then
    echo "ERROR: external setup fixture requires Bazel 7.7.1; found $(bazel --version)." >&2
    exit 1
  fi
  bazel \
    --output_user_root="$temporary_root/output-user-root" \
    test \
    --noenable_bzlmod \
    --incompatible_use_python_toolchains=false \
    --python_path="$python_path" \
    --repository_cache="$temporary_root/repository-cache" \
    --experimental_convenience_symlinks=ignore \
    --test_output=errors \
    //:external_setup_smoke_test \
    //:external_verilog_test
)
