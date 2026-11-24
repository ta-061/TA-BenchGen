#!/usr/bin/env python3
"""Check that the saved results are consistent with the benchmark and with each other.

    uv run python results/check.py

Verifies: the analyzed sources are the benchmark sources; label positions point at code;
every TEE Flow Inspector repetition identified its own sinks, built its own candidates and judged
all of them with the pinned model, sharing no response with another repetition; every
static-analysis stage succeeded.
"""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

R = Path(__file__).resolve().parent
B = R.parent / "benchmark"
TFI = R / "tee-flow-inspector-gpt52"
RUNS = ("run-01", "run-02", "run-03")
SINGLE_RUN = {"T33"}  # measured once
MODEL = "gpt-5.2-2025-12-11"
problems = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cases = json.loads((R / "cases.json").read_text())
    if {p.name for p in (B / "defective").glob("case_*")} != {c["case"] for c in cases.values()}:
        problems.append("cases.json does not list benchmark/defective exactly")
    flow_inputs = json.loads((TFI / "inputs.json").read_text())
    static_inputs = json.loads((R / "diting-codeql-semgrep/inputs.json").read_text())
    files = 0
    for ta, case in cases.items():
        for name, record in (("tee-flow", flow_inputs[ta]), ("static", static_inputs[ta])):
            if record["source"] != case["source"]:
                problems.append(f"{ta}: {name} analyzed another source")
            for file, digest in record["files"].items():
                files += 1
                if sha(B / case["source"] / file) != digest:
                    problems.append(f"{ta}: {name} input {file} differs from the benchmark")
        if not set(flow_inputs[ta]["files"]) <= set(static_inputs[ta]["files"]) or flow_inputs[ta]["gp_1_1"] != static_inputs[ta]["gp_1_1"]:
            problems.append(f"{ta}: the two tool families saw different inputs")
    labels = list(csv.DictReader((R / "summary/labels.csv").open(encoding="utf-8-sig")))
    for row in labels:
        lines = (B / cases[row["ta_id"]]["source"] / row["path"]).read_text(errors="replace").splitlines()
        first, last = int(row["first_line"]), int(row["last_line"])
        if not 1 <= first <= last <= len(lines) or not any(
                x.strip() and not x.strip().startswith(("//", "/*", "*")) for x in lines[first - 1:last]):
            problems.append(f"label does not point at code: {row}")

    responses, delivered, function_lists = defaultdict(set), Counter(), defaultdict(set)
    for run in RUNS:
        for ta in cases:
            folder = TFI / "pkcs11-T33" if ta in SINGLE_RUN else TFI / run / "cases" / ta
            if ta in SINGLE_RUN and run != RUNS[0]:
                continue
            attempts = sorted(folder.glob("attempt-*"))
            done = [a for a in attempts if json.loads((a / "run.json").read_text())["status"] == "completed"]
            if len(done) != 1:
                problems.append(f"{run}/{ta}: {len(done)} completed attempts")
                continue
            attempt, record = done[0], json.loads((done[0] / "run.json").read_text())
            native = attempt / "outputs/results_1"
            candidates = json.loads((native / "ta_candidate_flows.json").read_text())
            coverage = json.loads((attempt / "coverage.json").read_text())
            if not (coverage["passed"] and coverage["expected_flow_count"] == coverage["recorded_flow_count"]
                    == len(candidates) == record["flows"]):
                problems.append(f"{run}/{ta}: not every candidate flow was judged")
            findings = json.loads((native / "ta_vulnerabilities.json").read_text())
            if len(findings["vulnerabilities"]) != record["findings"] or findings.get("llm_model") != MODEL:
                problems.append(f"{run}/{ta}: finding count or model")
            logs = [attempt / "api-usage.jsonl"]
            if ta not in SINGLE_RUN:
                # every repetition identified its own sinks and built its own candidates from them
                function_lists[ta].add(sha(native / "ta_phase12.json"))
                screening = json.loads((native / "ta_sinks.json").read_text())
                calls = [json.loads(x) for x in (attempt / "phase3/api-usage.jsonl").read_text().splitlines()] \
                    if (attempt / "phase3/api-usage.jsonl").is_file() else []
                if screening["analysis_time"]["functions_analyzed"] != sum(c["event"] == "delivered" for c in calls) \
                        or len(screening["sinks"]) != record["sinks"]:
                    problems.append(f"{run}/{ta}: sink identification incomplete")
                command = json.loads((native / "phase4-command.json").read_text())
                if "/results/cases/%s/%s/outputs/results_1" % (ta, attempt.name) not in " ".join(command):
                    problems.append(f"{run}/{ta}: candidates were not built in this attempt")
                logs.append(attempt / "phase3/api-usage.jsonl")
            if candidates and not logs[0].is_file():
                problems.append(f"{run}/{ta}: no API record")
            for log in logs:
                for line in log.read_text().splitlines() if log.is_file() else []:
                    event = json.loads(line)
                    if event.get("event") == "delivered":
                        delivered[event.get("model"), event.get("source")] += 1
                        responses[run].add(event["response_id"])
    for ta, digests in function_lists.items():
        if len(digests) != 1:
            problems.append(f"{ta}: the function list (no LLM) differs between repetitions")
    shared = sum(len(responses[a] & responses[b]) for a, b in (("run-01", "run-02"), ("run-01", "run-03"), ("run-02", "run-03")))
    if shared or set(delivered) - {(MODEL, "live")}:
        problems.append(f"responses shared between runs: {shared}; sources: {dict(delivered)}")

    for ta in cases:
        commands = json.loads((R / "diting-codeql-semgrep/cases" / ta / "commands.json").read_text())
        passed = {c["stage"] for c in commands if c.get("exit_code") == 0}
        compiled = [c for c in commands if c["stage"] == "compile-plan"]
        if not {"database-create", "diting", "diting-memflow", "codeql"} <= passed or not {"semgrep", "semgrep-retry"} & passed \
                or sum(c["stage"] == "diting-query" and c["exit_code"] == 0 for c in commands) != 6:
            problems.append(f"diting-codeql-semgrep/{ta}: a stage failed")
        if sum("--target=aarch64-none-elf" in c["argv"] for c in compiled) != sum(
                f.startswith("ta/") and f.endswith(".c") for f in static_inputs[ta]["files"]):
            problems.append(f"diting-codeql-semgrep/{ta}: not every TA source was compiled")
        if any("-D__OPTEE_CORE_API_COMPAT_1_1=1" in c["argv"] for c in compiled) != static_inputs[ta]["gp_1_1"]:
            problems.append(f"diting-codeql-semgrep/{ta}: GP 1.1 flag")
    print(f"{len(cases)} TAs, {files} input files, {len(labels)} label positions, "
          f"{ {run: len(ids) for run, ids in responses.items()} } API responses")
    for problem in problems:
        print("NG", problem)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return bool(problems)


if __name__ == "__main__":
    sys.exit(main())
