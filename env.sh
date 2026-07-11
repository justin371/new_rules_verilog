#!/usr/bin/env bash

if ! PROJ_DIR="$(git rev-parse --show-toplevel 2>&1)"; then
  printf 'Error: env.sh must be sourced from a rules_verilog checkout: %s\n' "$PROJ_DIR" >&2
  return 1 2>/dev/null || exit 1
fi
export PROJ_DIR

export SIMRESULTS="${SIMRESULTS:-/nfs/regression}"
export TEST_TMPDIR="${TEST_TMPDIR:-${SIMRESULTS}}"

GLOBAL_TOOLS="${GLOBAL_TOOLS:-/global/tools}"

if ! module load git/2.33 lsf/10.1 bazel/7.7.1; then
  echo "Error: failed to load the required Git, LSF, and Bazel 7.7.1 modules." >&2
  return 1 2>/dev/null || exit 1
fi

ANACONDA_ENV_SCRIPT="${GLOBAL_TOOLS}/freeware/anaconda3/2024.02/anaconda3vars.sh"
if [[ ! -r "$ANACONDA_ENV_SCRIPT" ]]; then
  echo "Error: Anaconda environment script is not readable: $ANACONDA_ENV_SCRIPT" >&2
  return 1 2>/dev/null || exit 1
fi
source "$ANACONDA_ENV_SCRIPT"

export CONDA_ENV="${CONDA_ENV:-sun}"

# Activate only when the requested environment is not already active.
if [[ "${CONDA_DEFAULT_ENV:-}" != "$CONDA_ENV" ]]; then
  if ! conda activate "${CONDA_ENV}"; then
    echo "Error: failed to activate conda environment ${CONDA_ENV}." >&2
    return 1 2>/dev/null || exit 1
  fi
fi
