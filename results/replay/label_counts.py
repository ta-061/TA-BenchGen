"""Count saved final reports against the benchmark. Does not run any analyzer."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from dataclasses import asdict, dataclass
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote

RESULTS = Path(__file__).resolve().parents[1]
REPO = RESULTS.parent
BENCH = REPO / "benchmark"
STATIC = RESULTS / "2026-11-21"
GP11 = RESULTS / "diting-gp11"
LLM = RESULTS / "llm-e12-qwen"
sys.path.insert(0, str(REPO / "src"))

from ta_bench.common.jsonio import atomic_json, load_json  # noqa: E402
from ta_bench.common.sources import source_digest  # noqa: E402
from ta_bench.dataset.reviews import defect_statuses, defect_versions, read_review  # noqa: E402
from ta_bench.dataset.store import approval_hashes  # noqa: E402

TITLES = {"UDO": "Unencrypted Data Output", "IVW": "Input Validation Weakness",
          "DUS": "Shared Memory Overwrite"}
LLM_CLASSES = {"unencrypted_data_output": "UDO", "input_validation_weakness": "IVW",
               "direct_usage_of_shared_memory": "DUS"}
CLASSES = ("IVW", "UDO", "DUS", "ORDER", "unmapped")
METHODS = ("DITING", "DITING-GP11", "CodeQL", "Semgrep", "TFI-Qwen")
MAPPED = {m: set(TITLES) if m in ("DITING", "DITING-GP11", "TFI-Qwen") else set()
          for m in METHODS}
COUNTS = ("total", "within_public", "same_public", "within_approved", "same_approved")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def rows(path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def index(rows_, key):
    out = {r[key]: r for r in rows_}
    check(len(out) == len(rows_), f"Duplicate {key}")
    return out


@dataclass(frozen=True)
class Target:
    defect: str
    category: str
    decision: str
    role: str
    path: str
    first: int
    last: int
    function: str
    public: bool
    approved: bool


def targets_for(folder, normal):
    stored = load_json(folder / "labels.json")
    working, _ = read_review(folder, stored)
    check(stored["case_id"] == folder.name and stored["normal"]["path"] == normal,
          f"Case or control ID mismatch: {folder}")
    check(stored["normal"]["source_digest"] == source_digest(BENCH / normal),
          f"Control digest mismatch: {folder}")
    review = working["review"]["status"]
    statuses = dict.fromkeys((d["id"] for d in stored["defects"]), "unreviewed")
    if (folder / "label_history.json").is_file():
        hashes = approval_hashes(folder, BENCH / normal, labels=working)
        statuses = defect_statuses(working, hashes, defect_versions(working, hashes))
        check(set(statuses.values()) <= {"approved", "rejected", "unreviewed", "in_review"},
              f"Stale label: {folder}")
    else:
        check(review == "unreviewed", f"Missing review history: {folder}")
    check((folder.parent.name == "rejected") == (review == "rejected"),
          f"Review and benchmark folder disagree: {folder}")
    targets, names = [], []
    for published, reviewed in zip(stored["defects"], working["defects"], strict=True):
        did, category = published["id"], published["class"]
        check(did == reviewed["id"] and category in CLASSES[:-1], f"Unexpected label: {folder}/{did}")
        example = published.get("order_example")
        names.append(f"{category}({example})" if example else category)
        def keys(defect):
            return [(t["role"], t["path"], *t["lines"], t["function"])
                    for t in defect["detector_targets"]]
        public = keys(published)
        approved = keys(reviewed) if statuses[did] == "approved" else []
        for key in dict.fromkeys(public + approved):
            targets.append(Target(did, category, statuses[did], *key, key in public, key in approved))
    return review, names, targets


def case_metadata(key, manifest, static, folders, commit):
    source = Path(manifest[key]["source"])
    normal_id = static["normal_id"]
    normal = manifest[normal_id]["source"]
    check(source.as_posix() == static["source"], f"Input differs for {key}")
    if source.parts[0] == "normal":
        check(key == normal_id, f"Unexpected normal mapping: {key}")
        root = BENCH / source
        scope = "current" if root.is_dir() else "retired_normal"
        review, names, targets, case_id = "normal", ["正常"], [], ""
    else:
        check(source.parts[0] == "defective" and source.name == "source", f"Unknown input: {source}")
        case_id = source.parent.name
        folder = folders[case_id]
        scope = "rejected" if folder.parent.name == "rejected" else "current"
        review, names, targets = targets_for(folder, normal)
        root = folder / "source"
    lengths = {}
    for relative, expected in manifest[key]["files"].items():
        if scope == "retired_normal":
            spec = f"{commit}:benchmark/{source.as_posix()}/{relative}"
            data = subprocess.check_output(["git", "-C", str(REPO), "show", spec])
        else:
            data = (root / relative).read_bytes()
        check(sha256(data).hexdigest() == expected, f"Input SHA-256 mismatch: {key}/{relative}")
        lengths[relative] = len(data.splitlines())
    for target in targets:
        check(1 <= target.first <= target.last <= lengths[target.path], f"Invalid target: {key}/{target}")
    info = dict(id=key, ta=Path(normal).name + "_" + "+".join(names), scope=scope,
                review=review, case_id=case_id, normal_id=normal_id, original_source=source.as_posix(),
                benchmark_source=None if scope == "retired_normal" else root.relative_to(REPO).as_posix())
    return info, targets, lengths


def issue(ref, native, category, locations, rule_ids=None):
    return dict(ref=ref, rule=native, category=category, locations=locations, rule_ids=rule_ids or [native])


def diting(data, key):
    lines = data.decode().splitlines()
    check(len(lines) == 2 * len(TITLES), f"Truncated DITING output: {key}")
    reports = []
    pattern = rf"file://[^:\n]*/sources/{key}/([^:\n]+):(\d+):(\d+):(\d+):(\d+)$"
    for i, (category, title) in enumerate(TITLES.items()):
        values = ast.literal_eval(lines[2*i + 1])
        check(isinstance(values, list) and lines[2*i] == f"{title}: {len(values)}",
              f"DITING heading differs from the reports: {key}/{title}")
        for j, raw in enumerate(values, 1):
            m = re.search(pattern, raw)
            check(m, f"Invalid DITING location: {raw}")
            path, start, col, end, end_col = m.groups()
            reports.append(issue(f"{category}[{j}]", title, category,
                                 [(unquote(path), int(start), int(end), int(col), int(end_col))]))
    return reports


def sarif(data):
    reports = []
    for i, run in enumerate(json.loads(data)["runs"], 1):
        for j, finding in enumerate(run["results"], 1):
            locations = []
            for loc in finding["locations"]:
                physical = loc["physicalLocation"]
                region = physical["region"]
                path = unquote(physical["artifactLocation"]["uri"])
                locations.append((path, region["startLine"], region.get("endLine", region["startLine"]),
                                  region.get("startColumn"), region.get("endColumn")))
            reports.append(issue(f"run {i} / result {j}", finding["ruleId"], "unmapped", locations))
    return reports


def semgrep(data):
    output = json.loads(data)
    reports = []
    for i, finding in enumerate(output["results"], 1):
        start, end = finding["start"], finding["end"]
        reports.append(issue(f"result {i}", finding["check_id"], "unmapped",
                             [(finding["path"], start["line"], end["line"], start.get("col"), end.get("col"))]))
    return reports, output["errors"]


def qwen(base, key, counts):
    data = load_json(base / "ta_vulnerabilities.json")
    coverage = load_json(base.parents[1] / "coverage.json")
    findings = data["vulnerabilities"]
    check(coverage["passed"] is True and coverage["expected_flow_count"] == int(counts["flows"])
          and coverage["recorded_flow_count"] == int(counts["flows"]), f"LLM coverage: {key}")
    check(len(findings) == data["total_vulnerability_lines"] == int(counts["findings"]),
          f"LLM consolidated count differs: {key}")
    index(findings, "vulnerability_id")
    reports = []
    for f in findings:
        line, rule = f["line"], f["primary_rule_id"]
        path = Path(f["file"]).relative_to("/inputs", key).as_posix()
        check(rule in f["rule_ids"], f"LLM primary rule missing: {key}")
        reports.append(issue(f["vulnerability_id"], rule, LLM_CLASSES.get(rule, "unmapped"),
                             [(path, line, line, None, None)], f["rule_ids"]))
    return reports


def read_outputs(key, static, gp, llm, archive):
    paths = [STATIC / "diting" / f"{key}.txt", GP11 / "diting" / f"{key}.txt",
             STATIC / "codeql" / f"{key}.sarif.gz", STATIC / "semgrep" / f"{key}.json"]
    payloads = [p.read_bytes() for p in paths]
    payloads[2] = gzip.decompress(payloads[2])
    for i in (0, 2, 3):
        rel = paths[i].relative_to(STATIC).as_posix()
        check(sha256(payloads[i]).hexdigest() == archive[rel], f"Raw output differs: {rel}")
    sg_reports, diagnostics = semgrep(payloads[3])
    tools = [diting(payloads[0], key), diting(payloads[1], key), sarif(payloads[2]), sg_reports]
    states = [static["diting_status"], "completed", static["codeql_status"], static["semgrep_status"]]
    check(all(s == "completed" for s in states[:3]) and states[3] in ("completed", "partial"),
          f"Unexpected static status: {key}/{states}")
    check(len(diagnostics) == int(static["semgrep_diagnostics"])
          and bool(diagnostics) == (states[3] == "partial"), f"Semgrep diagnostics: {key}")
    check([len(r) for r in tools] == [int(static["diting"]), int(gp["warnings_after"]),
                                      int(static["codeql"]), int(static["semgrep"])], f"Tool totals: {key}")
    for c in TITLES:
        before = sum(r["category"] == c for r in tools[0])
        after = sum(r["category"] == c for r in tools[1])
        check(before == int(static[f"diting_{c}"]) == int(gp[f"{c}_before"])
              and after == int(gp[f"{c}_after"]), f"DITING class count: {key}/{c}")
    llm_state = llm["status"]
    states.append(llm_state)
    if llm_state == "completed":
        base = LLM / llm["output"]
        check(base.resolve().is_relative_to((LLM / "cases" / key).resolve()), f"LLM path: {key}")
        paths.append(base / "ta_vulnerabilities.json")
        tools.append(qwen(base, key, llm))
    else:
        check(llm_state in ("running", "pending", "failed") and llm["findings"] == "",
              f"Unknown or inconsistent LLM state: {key}")
        paths.append(None)
        tools.append(None)
    return zip(METHODS, states, paths, tools, strict=True)


def summarize(info, targets, lengths, method, state, path, reports):
    source = path.relative_to(REPO).as_posix() if path else None
    scoped = {s: [t for t in targets if getattr(t, s)] for s in ("public", "approved")}
    classes = MAPPED[method]
    counts = Counter()
    per_target = Counter()
    matched_labels = {s: set() for s in scoped}
    matched_same = {s: set() for s in scoped}
    evidence = []
    for r in reports or ():
        category, locations = r["category"], r["locations"]
        check(locations and all(1 <= a <= b <= lengths[p] for p, a, b, _, _ in locations),
              f"Invalid report position: {info['id']}/{method}/{r['ref']}")
        hit = [t for t in targets if any(p == t.path and a <= t.last and b >= t.first
                                         for p, a, b, _, _ in locations)]
        per_target.update((t, category) for t in hit)
        counts["total", category] += 1
        refs = {}
        for s in scoped:
            selected = [t for t in hit if getattr(t, s)]
            same = [t for t in selected if t.category == category]
            counts[f"within_{s}", category] += bool(selected)
            counts[f"same_{s}", category] += bool(same)
            matched_labels[s].update(t.defect for t in selected)
            matched_same[s].update(t.defect for t in same)
            refs[s] = [f"{t.defect}/{t.category}/{t.role}" for t in selected]
        evidence.append(dict(id=info["id"], method=method, **r, **refs, source=source))
    summary = dict(info, method=method, status=state, output=source)
    for scope, ts in scoped.items():
        summary[f"labels_{scope}"] = len({t.defect for t in ts})
        comparable = {t.defect for t in ts if t.category in classes}
        summary[f"comparable_{scope}"] = len(comparable)
        summary[f"labels_hit_{scope}"] = len(matched_labels[scope]) if reports is not None and ts else None
        summary[f"labels_same_{scope}"] = len(matched_same[scope]) if reports is not None and comparable else None
    for measure in COUNTS:
        scope = measure.split("_")[-1]
        ts = scoped.get(scope, [])
        available = reports is not None and (measure == "total" or bool(ts))
        for c in CLASSES:
            applies = c in classes or c == "unmapped"
            if measure.startswith("same_"):
                applies = c in classes and any(t.category == c for t in ts)
            summary[f"{measure}_{c}"] = counts[measure, c] if available and applies else None
        if measure.startswith("same_"):
            available = available and any(t.category in classes for t in ts)
        summary[measure] = sum(counts[measure, c] for c in CLASSES) if available else None
    details = []
    for t in targets:
        hits = sum(per_target[t, c] for c in CLASSES)
        details.append(dict(id=info["id"], **asdict(t), method=method, status=state,
                            hits=hits if reports is not None else None,
                            same=per_target[t, t.category] if reports is not None and t.category in classes else None))
    return summary, details, evidence


def check_published_locations(details):
    targets = {(r["id"], r["defect"], r["category"], r["role"], r["path"], r["first"], r["last"], r["method"]): r
               for r in details if r["public"]}
    for directory, fields in ((STATIC, {"DITING": ("diting", "diting_same_class"),
                                        "CodeQL": ("codeql", None), "Semgrep": ("semgrep", None)}),
                              (GP11, {"DITING": ("hits_before", "same_class_before"),
                                      "DITING-GP11": ("hits_after", "same_class_after")})):
        for old in rows(directory / "locations.csv"):
            key = (old["id"], old["defect"], old["class"], old["role"], old["path"],
                   int(old["first_line"]), int(old["last_line"]))
            for method, (hit, same) in fields.items():
                new = targets[(*key, method)]
                check(new["hits"] == int(old[hit]), f"Archived location mismatch: {key}/{method}")
                if same:
                    check(new["same"] == (int(old[same]) if old[same] else None),
                          f"Archived category mismatch: {key}/{method}")


def extract():
    manifest = load_json(STATIC / "inputs.json")
    check(manifest == load_json(LLM / "inputs.json"), "LLM and static input manifests differ")
    static, gp, llm = (index(rows(base / "cases.csv"), "id") for base in (STATIC, GP11, LLM))
    check(manifest.keys() == static.keys() == gp.keys() == llm.keys(), "Different TA IDs across methods")
    status = load_json(LLM / "status.json")
    check(dict(Counter(r["status"] for r in llm.values())) == {s:n for s,n in status["counts"].items() if n},
          "LLM sync in progress: cases.csv and status.json disagree")
    stages = ("diting", "host", "switch", "arrayaccess", "ifstmt", "dataflow", "memory", "memflow")
    commands = [json.loads(line) for line in (GP11 / "commands.jsonl").read_text().splitlines()]
    expected_runs = Counter((key, stage) for key in manifest for stage in stages)
    check(Counter((r["id"], r["stage"]) for r in commands) == expected_runs
          and all(r["exit_code"] == 0 for r in commands), "Missing or failed GP11 run")
    archive = load_json(STATIC / "verification.json")["sha256_uncompressed_tool_output"]
    commit = load_json(STATIC / "environment.json")["git_commit"]
    folders = {}
    for group in ("defective", "rejected"):
        for folder in (BENCH / group).iterdir():
            if folder.is_dir():
                check(folder.name not in folders, f"Case appears in two folders: {folder.name}")
                folders[folder.name] = folder
    current_normals = {f"normal/{p.name}" for p in (BENCH / "normal").iterdir() if p.is_dir()}
    check(current_normals <= {v["source"] for v in manifest.values()}, "Current normal missing a measurement")
    cases, summaries, target_rows, reports = [], [], [], []
    for key in sorted(manifest):
        check(len({manifest[key]["source"], gp[key]["source"], llm[key]["source"]}) == 1
              and gp[key]["normal_id"] == static[key]["normal_id"], f"Conflicting input ID: {key}")
        info, targets, lengths = case_metadata(key, manifest, static[key], folders, commit)
        cases.append(info)
        for method, state, path, findings in read_outputs(key, static[key], gp[key], llm[key], archive):
            summary, details, evidence = summarize(info, targets, lengths, method, state, path, findings)
            summaries.append(summary)
            target_rows.extend(details)
            reports.extend(evidence)
    check(set(folders) == {r["case_id"] for r in cases if r["case_id"]}, "Unmeasured benchmark case")
    check_published_locations(target_rows)
    scopes = ("current", "rejected", "retired_normal")
    cases.sort(key=lambda r: (scopes.index(r["scope"]), r["normal_id"], r["review"] != "normal", r["ta"], r["id"]))
    order = {c["id"]: i for i, c in enumerate(cases)}
    summaries.sort(key=lambda r: (order[r["id"]], METHODS.index(r["method"])))
    return dict(cases=cases, methods=METHODS, classes=CLASSES, counts=summaries, targets=target_rows,
                reports=reports, llm_status=status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=RESULTS / "outputs/label-comparison/ta-method.csv")
    parser.add_argument("--json", type=Path, help="also export all inputs to the Excel report")
    args = parser.parse_args()
    data = extract()
    leading = ["ta", "id", "scope", "review", "normal_id", "method", "status", *COUNTS]
    columns = leading + [k for k in data["counts"][0] if k not in leading]
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.csv.parent) as work:
        temp = Path(work) / args.csv.name
        with temp.open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(data["counts"])
        temp.replace(args.csv)
    if args.json:
        atomic_json(args.json, data)
    print(f"{len(data['cases'])} TAs, {len(data['counts'])} TA/method rows, {len(data['reports'])} reports.")


if __name__ == "__main__":
    main()
