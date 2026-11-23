#!/bin/sh
set -eu
cd "$(dirname "$0")"
base=$(pwd -P)
exec /usr/bin/docker run --rm --pull never --name ta-bench-e12-worker --init --user "$(id -u):$(id -g)" \
  -v "$base/runtime/src:/workspace/src:ro" -v "$base/artifact/prompts:/workspace/prompts:ro" -v "$base/artifact/rules:/workspace/rules:ro" \
  -v "$base/ops:/ops:ro" -v "$base/support:/support:ro" -v /usr/lib/llvm-18/lib/clang/18:/support/clang:ro \
  -v "$base/inputs:/inputs:ro" -v "$base/work:/work" -v "$base/../TA-BenchGen/results/llm-e12-qwen:/results" \
  -w /work ta-bench-llm:e12 python /ops/worker.py
