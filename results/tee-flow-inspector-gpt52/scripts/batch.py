"""Run all six phases of TEE Flow Inspector from scratch for every TA of one repetition.

Each TA is processed independently and in parallel: function classification, sink identification
(GPT-5.2), candidate flows (GP 1.1 names added), flow judgment (GPT-5.2) and the report.
Nothing is taken over from another repetition or another measurement.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
import csv
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, "/audit")
from check_output import check
from response_audit import audit

OUT = Path("/results")
WORK = Path("/work")
PLAN = json.loads((OUT / "plan.json").read_text())
INPUTS = json.loads((OUT / "inputs.json").read_text())
SRC = "/workspace/src"


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def latest(ta):
    paths = sorted((OUT / "cases" / ta).glob("attempt-*/run.json"))
    return json.loads(paths[-1].read_text()) if paths else {}


def events(path):
    if not path.exists():
        return []
    with path.open("rb") as stream:
        return [json.loads(line) for line in stream if line.endswith(b"\n") and line.strip()]


def totals(ledger):
    usage = Counter()
    for row in ledger:
        if row.get("source") != "live" or not row.get("response_id"):
            continue
        costs = row["usage"]
        usage.update(live_responses=1, input_tokens=costs.get("input_tokens", 0),
                     cached_input_tokens=(costs.get("input_tokens_details") or {}).get("cached_tokens", 0),
                     output_tokens=costs.get("output_tokens", 0))
    return usage


def publish(mode="running"):
    rows, commands = [], []
    for ta in PLAN["cases"]:
        run = latest(ta)
        rows.append(dict(id=ta, source=INPUTS[ta]["source"], status=run.get("status", "pending"),
                         attempts=run.get("attempt", 0), sinks=run.get("sinks"), flows=run.get("flows"),
                         findings=run.get("findings"), sink_calls=run.get("sink_calls"),
                         flow_calls=run.get("flow_calls"), output=run.get("output")))
        for folder in sorted((OUT / "cases" / ta).glob("attempt-*")):
            commands.extend(events(folder / "phase-commands.jsonl"))
    counts = Counter(r["status"] for r in rows)
    state = dict(updated_utc=now(), status=mode, total=len(rows), completed=counts["completed"], counts=dict(counts),
                 running=[r["id"] for r in rows if r["status"] == "running"], model=PLAN["model"])
    if (WORK / "block.json").is_file():
        state["block"] = json.loads((WORK / "block.json").read_text())
    table = io.StringIO()
    writer = csv.DictWriter(table, fieldnames=rows[0], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    save(OUT / "commands.jsonl", "".join(json.dumps(c) + "\n" for c in sorted(commands, key=lambda c: c["started_utc"])))
    save(OUT / "cases.csv", table.getvalue())
    save(OUT / "status.json", state)


def analyze(ta):
    if (WORK / "block.json").exists():
        return
    root = OUT / "cases" / ta
    existing = sorted(root.glob("attempt-*"))
    number = int(existing[-1].name.split("-")[1]) + 1 if existing else 1
    attempt = root / f"attempt-{number:02d}"
    native = attempt / "outputs/results_1"
    native.mkdir(parents=True)
    (attempt / "phase3").mkdir()
    cache = WORK / "cache" / ta / str(number)  # a new attempt never replays an earlier response
    meta = dict(id=ta, attempt=number, status="running", started_utc=now(), model=PLAN["model"], prompt=PLAN["prompt"])
    save(attempt / "run.json", meta)
    project = Path("/inputs") / ta / "ta"
    phase12, sinks_file = native / "ta_phase12.json", native / "ta_sinks.json"
    flows, findings = native / "ta_candidate_flows.json", native / "ta_vulnerabilities.json"
    prompt = ["--prompt-version", PLAN["prompt"]]
    try:
        timings = []
        def stage(name, arguments, env=None):
            argv = list(map(str, [sys.executable, *arguments]))
            with (attempt / "phase-commands.jsonl").open("a") as out:
                print(json.dumps(dict(id=ta, stage=name, started_utc=now(), cwd=str(project), argv=argv,
                                      env=env or {})), file=out)
            start = time.monotonic()
            with (attempt / "run.log").open("ab") as log:
                process = subprocess.run(argv, cwd=project, stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, **(env or {})))
            timings.append(f"{name} seconds: {time.monotonic()-start:.3f}")
            if process.returncode == 77:
                raise InterruptedError("api_block")
            if process.returncode == 65:
                raise ValueError("incomplete_response")
            if process.returncode:
                raise ValueError(f"{name}_exit_{process.returncode}")
        stage("phase1-2", ["/eval/phase12.py", project, phase12])
        stage("phase3", ["/eval/invoke.py", ta, attempt / "phase3", cache / "phase3", "-i", phase12, "-o", sinks_file,
                         "--llm-only", *prompt], {"TA_PHASE_PROGRAM": "identify_sinks/identify_sinks.py"})
        stage("phase4", ["/eval/phase4.py", ta, native])
        stage("phase5", ["/eval/invoke.py", ta, attempt, cache / "phase5", "--flows", flows, "--phase12", phase12,
                         "--output", findings, *prompt])
        used = native / "ta_sinks_gp11.json"
        stage("phase6", [f"{SRC}/report/generate_report.py", "--sinks", used if used.exists() else sinks_file,
                         "--flows", flows, "--vulnerabilities", findings, "--phase12", phase12, "--project-name", ta,
                         "--output", native / "ta_vulnerability_report.html"])
        (native / "time.txt").write_text("\n".join(timings) + "\n")
        sink_calls = [c for c in events(attempt / "phase3/api-usage.jsonl") if c["event"] == "delivered"]
        flow_log = events(attempt / "api-usage.jsonl")
        delivered = [c for c in flow_log if c["event"] == "delivered"]
        save(attempt / "logical_calls.jsonl", "".join(json.dumps(
            dict(request_key=f"{c['request_key']}/{c['occurrence']}", delivered=True)) + "\n" for c in delivered))
        coverage = check(attempt, audit(native / "conversations.jsonl"))
        save(attempt / "coverage.json", coverage)
        if not coverage["passed"] or bool(coverage["expected_flow_count"]) != bool(delivered):
            raise ValueError("coverage_failed")
        screening = json.loads(sinks_file.read_text())
        if screening["analysis_time"]["functions_analyzed"] != len(sink_calls):
            raise ValueError("sink_screening_incomplete")
        results = json.loads(findings.read_text())
        if len(results["vulnerabilities"]) != results["total_vulnerability_lines"]:
            raise ValueError("consolidation_mismatch")
        usage = totals(events(attempt / "phase3/api-usage.jsonl")) + totals(flow_log)
        meta.update(status="completed", sinks=len(screening["sinks"]), flows=coverage["recorded_flow_count"],
                    findings=len(results["vulnerabilities"]), output=str(native.relative_to(OUT)),
                    sink_calls=len(sink_calls), flow_calls=len(delivered), usage=dict(usage))
    except InterruptedError as exc:
        meta.update(status="interrupted", reason=str(exc))
    except Exception as exc:
        meta.update(status="failed", reason=str(exc)[:240])
    finally:
        meta["finished_utc"] = now()
        save(attempt / "run.json", meta)


def main():
    lock = (WORK / "batch.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cohort = list(PLAN["cases"])
    for ta in cohort:
        old = latest(ta)
        if old.get("status") == "running":
            old.update(status="interrupted", reason="service_restart", finished_utc=now())
            save(OUT / "cases" / ta / f"attempt-{old['attempt']:02d}" / "run.json", old)
    for wave in range(PLAN.get("max_attempt_waves", 2)):
        targets = [ta for ta in cohort if latest(ta).get("status") != "completed"]
        if not targets or (WORK / "block.json").exists():
            break
        with ThreadPoolExecutor(max_workers=PLAN["max_workers"]) as executor:
            futures = {executor.submit(analyze, ta) for ta in targets}
            while futures:
                publish()
                finished, futures = wait(futures, timeout=5)
                for job in finished:
                    job.result()
    blocked = (WORK / "block.json").exists()
    done = all(latest(ta).get("status") == "completed" for ta in cohort)
    publish("completed" if done else "blocked" if blocked else "finished_with_failures")
    return 77 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
