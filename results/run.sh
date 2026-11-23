#!/usr/bin/env bash
# Replay one recorded TA. Use the same command on the Mac and on Kali.
set -euo pipefail
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo 'Usage: ./results/run.sh T18  (Mac: static analyzers, Kali/Linux: LLM)'
  exit 0
fi
if [[ $# != 1 ]]; then echo 'Usage: ./results/run.sh T18' >&2; exit 2; fi

ta=$1
results=$(cd "$(dirname "$0")" && pwd -P)
case $(uname -s) in
  Darwin) dataset=2026-11-21 ;;
  Linux)  dataset=llm-e12-qwen ;;
  *) echo 'Use the static-analysis Mac or the LLM Linux host.' >&2; exit 2 ;;
esac
if ! jq -e --arg ta "$ta" 'has($ta)' "$results/$dataset/inputs.json" >/dev/null; then
  echo "Unknown TA: $ta (see $dataset/inputs.json)" >&2
  exit 2
fi

# The original drivers expect the measured benchmark beside their results directory.
work=$(mktemp -d "${TMPDIR:-/tmp}/ta-bench-$ta.XXXXXXXX")
work=$(cd "$work" && pwd -P)
echo "Output: $work"
revision=$(jq -er .git_commit "$results/2026-11-21/environment.json")
git -C "$results/.." archive "$revision" benchmark | tar -xf - -C "$work"
bundle="$work/results/$dataset"
mkdir -p "$bundle"
cp -R "$results/$dataset/replay" "$results/$dataset/inputs.json" "$bundle/"

if [[ $dataset == llm-e12-qwen ]]; then
  cp "$results/$dataset/profile.json" "$bundle/"
  exec python3 "$bundle/replay/run-case.py" "$ta" --work "$work/llm"
fi

# Published DITING, standard CodeQL and Semgrep share the measured source snapshot.
cp "$results/$dataset/"{build-config.txt,environment.json} "$bundle/"
"${TA_PYTHON:-python3.11}" "$bundle/replay/run.py" "$ta" --work "$work/static"

# For the GP 1.1 condition, apply the recorded patch to a copy and reuse the database.
gp="$work/gp11"
job="$gp/jobs/$ta"
mkdir -p "$job/out"
cp -R "$work/static/jobs/$ta/tee_example" "$job/"
cp -R "$work/static/query" "$work/static/deps/diting/real_world_analysis.py" "$gp/"
cd "$gp"
patch -s -p1 -i "$results/diting-gp11/rules.patch"
jq -r '.sha256 | to_entries[] | "\(.value)  \(if .key == "real_world_analysis.py" then .key else "query/"+.key end)"' \
  "$results/diting-gp11/environment.json" | shasum -a 256 -c -
export PATH="$work/static/bin:$PATH" DITING_CACHE="$work/static/deps/query-cache"
CODEQL_DIST=$(cd "$work/static/deps/codeql" && pwd -P)
export CODEQL_DIST DITING_CLI="$CODEQL_DIST/codeql" DITING_TRACE="$job/queries.jsonl"
python=$(jq -er '.[] | select(.stage == "diting") | .argv[0]' "$work/static/jobs/$ta/commands.json")
cd "$job"
"$python" "$gp/real_world_analysis.py" > diting.txt 2> diting.log
codeql query run ../../query/memflow.ql --database=tee_example > out/memflow.out 2> memflow.log
jq -es 'length == 7 and all(.[]; .exit_code == 0)' "$DITING_TRACE" >/dev/null
echo "GP 1.1: $job/diting.txt"
