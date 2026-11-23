#!/usr/bin/env python3.11
"""Replay the recorded static measurements in an empty working directory."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent
os.environ["BENCHMARK_DIR"] = str(RESULTS.parents[1] / "benchmark")
import measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    manifest = json.loads((RESULTS / "inputs.json").read_text())
    parser.add_argument("case", choices=["all", *manifest])
    parser.add_argument("--work", type=Path, help="new or empty output directory")
    args = parser.parse_args()
    default = (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ta-benchgen-static/2026-11-21"
    )
    tools = Path(os.environ.get("TA_MEASURE_TOOLS", default)).resolve()
    if not (tools / "venv/bin/semgrep").is_file():
        parser.error("run setup.sh first or set TA_MEASURE_TOOLS")
    if sys.version_info[:3] != (3, 11, 10):
        parser.error("use the measured Python 3.11.10 interpreter from setup.sh")
    os.environ.update(
        CODEQL_DIST=str((tools / "codeql").resolve()),
        LLVM_DIST=str((tools / "llvm").resolve()),
        SEM_BIN=str(tools / "venv/bin"),
        TA_DEV_KIT_DIR=str(tools / "devkit"),
        TEEC_INCLUDE=str(tools / "client"),
        TA_CONF=str(RESULTS / "build-config.txt"),
        DITING_ROOT=str(tools / "diting"),
        SEMGREP_CONFIG=str(tools / "semgrep-c.yaml"),
        HOST_CC="/usr/bin/clang",
    )
    work = (
        args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="ta-benchgen-static-")).resolve()
    )
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        parser.error(f"choose an empty output directory: {work}")
    print("Working directory:", work, flush=True)
    shutil.copyfile(HERE / "compile.py", work / "compile.py")
    entries = measure.prepare(work)
    if entries != manifest:
        raise ValueError("Input hashes differ from the recorded benchmark")
    reference = json.loads((RESULTS / "environment.json").read_text())
    for name, expected in reference["diting"]["files_sha256"].items():
        path = tools / "diting" / name if name.endswith(".py") else work / "query" / name
        if measure.digest(path) != expected:
            raise ValueError(f"DITING file differs from the measurement: {name}")
    order = sorted(entries, key=lambda k: -len(entries[k]["files"])) if args.case == "all" else [args.case]
    with ThreadPoolExecutor(max_workers=reference["jobs"]) as pool:
        list(pool.map(lambda k: measure.run_case(work, k), order))
    for key in order:
        job = work / "jobs" / key
        stages = json.loads((job / "commands.json").read_text())
        queries = [json.loads(line) for line in (job / "query-calls.jsonl").read_text().splitlines()]
        if len(stages) != 5 or len(queries) != 6 or any(x["exit_code"] for x in [*stages, *queries]):
            raise RuntimeError(f"{key} did not finish all commands; see {job}/logs")
    print("Outputs:", work / "jobs")


if __name__ == "__main__":
    main()
