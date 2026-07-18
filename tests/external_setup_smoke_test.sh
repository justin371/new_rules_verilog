#!/usr/bin/env bash
set -Eeuo pipefail

trap 'status=$?; printf "ERROR: external_setup_smoke_test.sh failed at line %s: %s (exit %s)\n" "$LINENO" "$BASH_COMMAND" "$status" >&2; exit "$status"' ERR

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
fixture_dir="$repo_root/tests/external_setup_smoke"
temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/rules_verilog_external_setup.XXXXXX")"
http_archive_fixture_dir="$temporary_root/http-archive-consumer"

cleanup() {
  rm -rf -- "$temporary_root"
}
trap cleanup EXIT

python_path="$(command -v python3.12)"

run_fixture() {
  local fixture_path=$1
  local output_root=$2
  (
    cd "$fixture_path"
    bazel \
      --output_user_root="$output_root" \
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
}

if [[ "$(bazel --version)" != "bazel 7.7.1" ]]; then
  echo "ERROR: external setup fixture requires Bazel 7.7.1; found $(bazel --version)." >&2
  exit 1
fi

run_fixture "$fixture_dir" "$temporary_root/local-output-user-root"

"$python_path" "$fixture_dir/prepare_http_archive_fixture.py" \
  --repository-root "$repo_root" \
  --fixture-dir "$fixture_dir" \
  --output-root "$temporary_root"

run_fixture "$http_archive_fixture_dir" "$temporary_root/http-archive-output-user-root"
