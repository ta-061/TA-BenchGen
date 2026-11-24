#!/bin/sh
# Run one repetition (run-NN): all phases from scratch for every TA in run-NN/plan.json, in parallel.
# Each repetition has its own work directory, so it never reuses a response of another repetition.
# Usage: run-batch.sh run-02   (TA_MEASURE_HOME: TEE Flow Inspector checkout, inputs and devkit)
set -eu
run=$1
scripts=$(cd "$(dirname "$0")" && pwd -P)
root=$(dirname "$scripts")
result="$root/$run"
base=${TA_MEASURE_HOME:-"$root/../../../ta-llm-eval"}
work=${TA_GPT_WORK_ROOT:-"$base/../ta-llm-eval-gpt52-full"}/$run/work
secret=${TA_OPENAI_KEY_FILE:-"$HOME/.config/ta-benchgen/openai.key"}
mkdir -p "$work"
[ -f "$work/llm_config.json" ] || cp "$root/llm_config.json" "$work/llm_config.json"
exec /usr/bin/docker run --rm --pull never --init --name "ta-bench-tfi-gpt52-$run" --user "$(id -u):$(id -g)" \
    -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONUNBUFFERED=1 -e PYTHONPATH=/workspace/src -e TA_DEV_KIT_DIR=/support/devkit \
    -v "$base/runtime/src:/workspace/src:ro" -v "$work/llm_config.json:/workspace/src/llm_settings/llm_config.json:ro" \
    -v "$base/artifact/prompts:/workspace/prompts:ro" -v "$base/artifact/rules:/workspace/rules:ro" \
    -v "$base/ops/check_output.py:/audit/check_output.py:ro" -v "$base/ops/response_audit.py:/audit/response_audit.py:ro" \
    -v "$base/support:/support:ro" -v /usr/lib/llvm-18/lib/clang/18:/support/clang:ro \
    -v "$base/inputs:/inputs:ro" -v "$secret:/secrets/openai.key:ro" -v "$work:/work" \
    -v "$result:/results" -v "$scripts:/eval:ro" -w /work ta-bench-llm:e12 python /eval/batch.py
