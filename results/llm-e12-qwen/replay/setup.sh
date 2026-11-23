#!/bin/bash
# Prepare an independent copy of the measured local-LLM runtime on Kali.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
tools=${TA_LLM_TOOLS:-"${XDG_DATA_HOME:-$HOME/.local/share}/ta-benchgen-e12"}
revision=e06f0c6dccbf1a30c10a79f3bbb0a92641f383e7
test -f /usr/lib/llvm-18/lib/clang/18/include/stddef.h || { echo 'Install clang-18 and libclang-common-18-dev first.' >&2; exit 1; }
provider="$tools/artifact/src/llm_settings/llm_config.json"
endpoint=${TA_LLM_BASE_URL:-}
if [[ -z $endpoint && -f $provider ]]; then
  endpoint=$(jq -r '.providers.local.base_url // empty' "$provider")
fi
endpoint=${endpoint:-$(jq -er '.providers.local.base_url' "$here/llm_config.json")}
mkdir -p "$tools/support/clang"
if [ ! -d "$tools/artifact" ]; then
  scratch=$(mktemp -d "$tools/.artifact.XXXXXX")
  trap 'rm -rf "$scratch"' EXIT
  git init -q "$scratch/artifact"
  git -C "$scratch/artifact" remote add origin https://github.com/ta-061/tee-bad-partitioning-llm-artifact.git
  git -C "$scratch/artifact" fetch -q --depth=1 origin "$revision"
  git -C "$scratch/artifact" checkout -q --detach FETCH_HEAD
  mv "$scratch/artifact" "$tools/artifact"
fi
test "$(git -C "$tools/artifact" rev-parse HEAD)" = "$revision"
settings=$(mktemp "$tools/.llm-config.XXXXXX")
jq --arg url "$endpoint" '.providers.local.base_url = $url' "$here/llm_config.json" > "$settings"
mv "$settings" "$provider"
python3 "$here/../../replay/headers.py" "$tools/support"
cp "$here/../../2026-11-21/build-config.txt" "$tools/support/conf.h"
printf '#undef CFG_TEE_TA_LOG_LEVEL\n#define CFG_TEE_TA_LOG_LEVEL 4\n' > "$tools/support/log-level.h"
docker build --platform linux/amd64 -t ta-bench-llm:e12-replay -f "$here/Dockerfile" "$here"
