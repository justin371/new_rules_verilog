#!/usr/bin/env bash

set -Eeuo pipefail

source_repo="${SOURCE_REPO:-${PWD}}"
expected_sha="${EXPECTED_SHA:?EXPECTED_SHA must be the GitHub workflow commit}"
rules_checkout="${RULES_CHECKOUT:-/u/lwang/rules_verilog}"
rules_branch="${RULES_BRANCH:-codex/v0.3-review-fixes}"
project_dir="${PROJECT_DIR:-/nfs/workspace/XinAnRiver/lwang/XinAnRiver}"
results_dir="${ETX_RESULTS_DIR:-/nfs/workspace/XinAnRiver/lwang/.rules_verilog_ci/manual-$(date +%Y%m%d-%H%M%S)}"
lock_file="${ETX_LOCK_FILE:-/u/lwang/.cache/rules_verilog-etx-vcs.lock}"

for directory in "${source_repo}" "${rules_checkout}" "${project_dir}"; do
    [[ -d "${directory}" ]] || {
        echo "required directory not found: ${directory}" >&2
        exit 2
    }
done

mkdir -p "$(dirname "${lock_file}")" "${results_dir}"

# Load the same ETX environment as the interactive `ss` alias before using
# LSF. Temporarily disable nounset because the site script is interactive-shell
# compatible but is not required to be `set -u` clean.
runner_working_dir="${PWD}"
cd "${project_dir}"
set +u
# shellcheck disable=SC1091
source env/digital_env.sh
set -Eeuo pipefail
cd "${runner_working_dir}"

for command in bsub flock git; do
    command -v "${command}" >/dev/null || {
        echo "required command not found after loading the ETX environment: ${command}" >&2
        exit 127
    }
done

exec 9>"${lock_file}"
flock -n 9 || {
    echo "another ETX rules_verilog validation is already running" >&2
    exit 75
}

git -C "${source_repo}" cat-file -e "${expected_sha}^{commit}"

if ! git -C "${rules_checkout}" diff --quiet ||
    ! git -C "${rules_checkout}" diff --cached --quiet; then
    echo "refusing to update ${rules_checkout}: tracked changes are present" >&2
    exit 3
fi

git -C "${rules_checkout}" fetch --no-tags "${source_repo}" "${expected_sha}"
if git -C "${rules_checkout}" show-ref --verify --quiet "refs/heads/${rules_branch}"; then
    git -C "${rules_checkout}" switch "${rules_branch}"
    git -C "${rules_checkout}" merge --ff-only "${expected_sha}"
else
    git -C "${rules_checkout}" switch -c "${rules_branch}" "${expected_sha}"
fi

actual_sha="$(git -C "${rules_checkout}" rev-parse HEAD)"
if [[ "${actual_sha}" != "${expected_sha}" ]]; then
    echo "rules_verilog checkout mismatch: expected ${expected_sha}, got ${actual_sha}" >&2
    exit 4
fi

printf '%s\n' \
    "workflow commit: ${expected_sha}" \
    "rules checkout: ${rules_checkout}" \
    "consumer project: ${project_dir}" \
    "results: ${results_dir}" >"${results_dir}/submission.txt"

job_name="rv-vcs-${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"
set +e
bsub \
    -K \
    -q syn \
    -J "${job_name}" \
    -oo "${results_dir}/lsf.log" \
    "${rules_checkout}/tests/etx_vcs_job.sh" \
    "${project_dir}" \
    "${results_dir}" \
    "${expected_sha}"
lsf_status=$?
set -e

echo "LSF exit code: ${lsf_status}" >>"${results_dir}/submission.txt"
exit "${lsf_status}"
