#!/usr/bin/env python3
"""Run one recorded e12 input against the local model in a fresh output directory."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent
BENCH = RESULTS.parents[1] / "benchmark"


def main():
    inputs = json.loads((RESULTS / "inputs.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=inputs)
    parser.add_argument("--work", type=Path, help="new or empty output directory")
    args = parser.parse_args()
    default = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ta-benchgen-e12"
    tools = Path(os.environ.get("TA_LLM_TOOLS", default)).resolve()
    artifact, support = tools / "artifact", tools / "support"
    provider = artifact / "src/llm_settings/llm_config.json"
    if not provider.is_file():
        parser.error("run setup.sh first or set TA_LLM_TOOLS")
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="ta-benchgen-e12-"))
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        parser.error(f"choose an empty output directory: {work}")
    key = args.case
    entry = inputs[key]
    project = work / "inputs" / key
    for name, digest in entry["files"].items():
        data = (BENCH / entry["source"] / name).read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"Benchmark source differs: {key}/{name}")
        dest = project / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    commands = json.loads((HERE / "compile-commands.json").read_text())[key]
    (project / "ta/compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    output = Path("cases") / key / "attempt-01/outputs"
    (work / "results" / output).mkdir(parents=True)
    (work / "work/calls").mkdir(parents=True)
    profile = json.loads((RESULTS / "profile.json").read_text())
    profile["base_url"] = json.loads(provider.read_text())["providers"]["local"]["base_url"]
    profile_path = work / "profile.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    argv = ["docker", "run", "--rm", "--pull", "never", "--init", "--user", f"{os.getuid()}:{os.getgid()}"]
    mounts = [
        (artifact / "src", "/workspace/src:ro"),
        (artifact / "prompts", "/workspace/prompts:ro"),
        (artifact / "rules", "/workspace/rules:ro"),
        (HERE, "/ops:ro"),
        (support, "/support:ro"),
        ("/usr/lib/llvm-18/lib/clang/18", "/support/clang:ro"),
        (work / "inputs", "/inputs:ro"),
        (work / "work", "/work"),
        (work / "results", "/results"),
        (profile_path, "/settings/profile.json:ro"),
    ]
    for source, dest in mounts:
        argv.extend(["-v", f"{source}:{dest}"])
    argv.extend(
        [
            "-w",
            "/work",
            "-e",
            "PYTHONPATH=/ops/hook:/workspace/src",
            "-e",
            "IISA_LOCAL_PROFILE=/settings/profile.json",
            "-e",
            "IISA_LOCAL_PRIVATE=/work/calls",
            "-e",
            "TA_DEV_KIT_DIR=/support/devkit",
            os.environ.get("TA_LLM_IMAGE", "ta-bench-llm:e12-replay"),
            "/usr/local/bin/python",
            "/ops/bootstrap.py",
            "/workspace",
            f"/inputs/{key}",
            f"/results/{output}",
            "/support/devkit",
        ]
    )
    print("Working directory:", work, flush=True)
    (work / "command.txt").write_text(shlex.join(argv) + "\n")
    with (work / "run.log").open("wb") as log:
        subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=True)
    print("Report:", work / "results" / output / "results_1/ta_vulnerability_report.html")


if __name__ == "__main__":
    main()
