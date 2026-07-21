#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="${1:?usage: etx_vcs_job.sh PROJECT_DIR RESULTS_DIR EXPECTED_SHA}"
results_dir="${2:?usage: etx_vcs_job.sh PROJECT_DIR RESULTS_DIR EXPECTED_SHA}"
expected_sha="${3:?usage: etx_vcs_job.sh PROJECT_DIR RESULTS_DIR EXPECTED_SHA}"

mkdir -p "${results_dir}"
cd "${project_dir}"

{
    echo "expected rules_verilog commit: ${expected_sha}"
    echo "project directory: ${project_dir}"
    echo "host: $(hostname)"
    echo "started: $(date --iso-8601=seconds)"
} >"${results_dir}/metadata.txt"

set +e
bazel test \
    --config=vcs \
    //... \
    --test_tag_filters=-no_ci_gate \
    --cache_test_results=no \
    --jobs 8 \
    --test_output=all 2>&1 | tee "${results_dir}/bazel-test.log"
bazel_status=${PIPESTATUS[0]}
set -e

echo "bazel exit code: ${bazel_status}" >>"${results_dir}/metadata.txt"
echo "finished: $(date --iso-8601=seconds)" >>"${results_dir}/metadata.txt"

set +e
testlogs_dir="$(bazel info bazel-testlogs 2>/dev/null | tail -n 1)"
set -e
if [[ -d "${testlogs_dir}" ]]; then
    (
        cd "${testlogs_dir}"
        find . -type f \( -name test.log -o -name test.xml \) -print0 |
            tar --null --files-from=- -czf "${results_dir}/bazel-testlogs.tar.gz"
    )
fi

grep -E \
    '(^|[[:space:]])(ERROR|FAIL|FAILED|WARNING):|Error-\[|[0-9]+ tests? FAILED|Executed [0-9]+ out of' \
    "${results_dir}/bazel-test.log" >"${results_dir}/failure-summary.txt" || true

exit "${bazel_status}"
