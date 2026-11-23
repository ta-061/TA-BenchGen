#!/bin/bash
# Install the pinned macOS tools into a user directory.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
tools=${TA_MEASURE_TOOLS:-"${XDG_DATA_HOME:-$HOME/.local/share}/ta-benchgen-static/2026-11-21"}
python=${TA_PYTHON:-python3.11}
"$python" -c 'import sys; assert sys.version_info[:3] == (3, 11, 10), "use TA_PYTHON to select Python 3.11.10"'
mkdir -p "$tools"
tmp=$(mktemp -d "$tools/.setup.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

install_archive() {
  local folder=$1 url=$2 checksum=$3
  if [ -d "$tools/$folder" ]; then return; fi
  curl -fL --retry 2 -o "$tmp/archive" "$url"
  (cd "$tmp" && printf '%s  archive\n' "$checksum" | shasum -a 256 -c -)
  mkdir "$tmp/$folder"
  tar -xf "$tmp/archive" -C "$tmp/$folder" --strip-components=1
  mv "$tmp/$folder" "$tools/$folder"
}
install_archive codeql \
  https://github.com/github/codeql-action/releases/download/codeql-bundle-v2.23.0/codeql-bundle-osx64.tar.gz \
  9ee7403acddb6bc18ccb7717a52d51e6fe30ff491ccd66012b11dc2cfe84d9f7
install_archive llvm \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-20.1.8/LLVM-20.1.8-macOS-ARM64.tar.xz \
  a9a22f450d35f1f73cd61ab6a17c6f27d8f6051d56197395c1eb397f0c9bbec4

if [ ! -d "$tools/diting" ]; then
  git init -q "$tmp/diting"
  git -C "$tmp/diting" remote add origin https://github.com/CharlieMCY/PartitioningE-in-TEE.git
  git -C "$tmp/diting" fetch -q --depth=1 --filter=blob:none origin cb72e8861809e70b7b820b0ece54d71f8ff93cd8
  git -C "$tmp/diting" checkout -q FETCH_HEAD -- query real_world_analysis.py
  mv "$tmp/diting" "$tools/diting"
fi
if [ ! -x "$tools/venv/bin/python" ]; then "$python" -m venv "$tools/venv"; fi
"$tools/venv/bin/python" -m pip install -c "$here/semgrep-constraints.txt" 'semgrep==1.164.0'
export BENCHMARK_DIR="$here/../../../benchmark"
"$python" "$here/fetch-rules.py" "$tmp/semgrep-c.yaml"
mv "$tmp/semgrep-c.yaml" "$tools/semgrep-c.yaml"
"$python" "$here/../../replay/headers.py" "$tools"
"$tools/codeql/codeql" version --format=json
"$tools/llvm/bin/clang" --version
"$tools/venv/bin/semgrep" --disable-version-check --version
