#!/usr/bin/env bash

export PROJ_DIR="$(git rev-parse --show-toplevel)"

export SIMRESULTS="/nfs/regression"
export TEST_TMPDIR=${SIMRESULTS}

GLOBAL_TOOLS=/global/tools

module load git/2.33
module load lsf/10.1
module load bazel/7.5.0

source ${GLOBAL_TOOLS}/freeware/anaconda3/2024.02/anaconda3vars.sh

export CONDA_ENV="sun"

# Conditionally activate the conda env
if [ ! -z "$CONDA_PROMPT_MODIFIER" ] || [ "$CONDA_PROMPT_MODIFIER" != "(${CONDA_ENV})" ]; then
  if ! conda activate "${CONDA_ENV}"; then
    echo "Error: Failed to activate conda environment ${CONDA_ENV}"
    exit 1
  fi
fi
