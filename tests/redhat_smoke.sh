#!/usr/bin/env bash
set -Eeuo pipefail

trap 'status=$?; printf "ERROR: redhat_smoke.sh failed at line %s: %s (exit %s)\n" "$LINENO" "$BASH_COMMAND" "$status" >&2; exit "$status"' ERR

if [[ ! -r /etc/os-release ]] || ! grep -Eqi '^(ID|ID_LIKE)=.*(rhel|fedora|centos|rocky|almalinux)' /etc/os-release; then
  echo "ERROR: this smoke test must run on a Red Hat-compatible Linux host." >&2
  exit 1
fi

python_path="$(command -v python3.12)"
"${python_path}" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'

if [[ "$(bazel --version)" != "bazel 7.7.1" ]]; then
  echo "ERROR: bazel 7.7.1 is required; found $(bazel --version)." >&2
  exit 1
fi

bazel test \
  --incompatible_use_python_toolchains=false \
  --python_path="${python_path}" \
  --test_output=errors \
  //:buildifier_diff //tests/... //examples/dpi:dpi_c_test
bazel build --config=vcs \
  //examples/apb:test \
  //examples/dpi:test \
  //tests/vcs_filelist_validation:rtl_lint_configured_vcs \
  //tests/vcs_filelist_validation:rtl_lint_configured_vcs_custom_rulefile \
  //tests/vcs_filelist_validation:rtl_lint_explicit_xrun \
  //tests/vcs_filelist_validation:rtl_svunit_explicit_xrun \
  //tests/vcs_filelist_validation:rtl_svunit_vcs
configured_lint_args="bazel-bin/tests/vcs_filelist_validation/rtl_lint_configured_vcs_cmds.tcl"
custom_lint_args="bazel-bin/tests/vcs_filelist_validation/rtl_lint_configured_vcs_custom_rulefile_cmds.tcl"
grep -F -- "-file vendors/synopsys/verilog_rtl_lint_default_opts.f" "${configured_lint_args}"
if grep -F -- "legacy_hal_rules.lint" "${configured_lint_args}"; then
  echo "ERROR: config-selected VCS lint retained the legacy HAL rulefile." >&2
  exit 1
fi
grep -F -- "-file tests/vcs_filelist_validation/custom_vcs_lint_opts.f" "${custom_lint_args}"
if grep -F -- "legacy_hal_rules.lint" "${custom_lint_args}"; then
  echo "ERROR: rulefile_vcs did not replace the legacy HAL rulefile." >&2
  exit 1
fi
configured_svunit="bazel-bin/tests/vcs_filelist_validation/rtl_svunit_vcs"
explicit_xrun_svunit="bazel-bin/tests/vcs_filelist_validation/rtl_svunit_explicit_xrun"
grep -F -- "runmod vcs -- runSVUnit" "${configured_svunit}"
grep -F -- "-s vcs" "${configured_svunit}"
grep -F -- "-f tests/vcs_filelist_validation/unit_test_top_vcs.f" "${configured_svunit}"
if grep -E "xcelium|runmod -t xrun" "${configured_svunit}"; then
  echo "ERROR: VCS SVUnit retained an Xcelium command." >&2
  exit 1
fi
grep -F -- "-s xcelium" "${explicit_xrun_svunit}"
if grep -F -- "-s vcs" "${explicit_xrun_svunit}"; then
  echo "ERROR: explicit XRUN SVUnit target was remapped to VCS." >&2
  exit 1
fi
bazel run //:buildifier_lint
./tests/doc_test.sh
bash ./tests/external_setup_smoke_test.sh
