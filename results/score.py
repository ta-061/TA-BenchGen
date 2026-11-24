#!/usr/bin/env python3
"""Compare the saved reports with the benchmark labels. Does not run any analyzer.

    uv run python results/score.py

A report matches a label position when it is in the same TA and file and its line range
overlaps the label's line range. "same" additionally requires the reported class to equal
the label class (DITING and TEE Flow Inspector report UDO, IVW or DUS; ORDER has no
corresponding reported class). TEE Flow Inspector was run three times, each time from sink
identification on; a location (file and line) reported in at least two runs counts as one detection, with the class
that at least two runs reported. T33 was run once and its single run is used as is.
Writes results/summary/*.csv and summary.md.
"""
import ast
from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote

RESULTS = Path(__file__).resolve().parent
REPO = RESULTS.parent
BENCH = REPO / "benchmark"
sys.path.insert(0, str(REPO / "src"))
from ta_bench.dataset.reviews import defect_statuses, defect_versions, read_review  # noqa: E402
from ta_bench.dataset.store import approval_hashes  # noqa: E402

DITING_TITLES = {"UDO": "Unencrypted Data Output", "IVW": "Input Validation Weakness", "DUS": "Shared Memory Overwrite"}
LLM_CLASSES = {"unencrypted_data_output": "UDO", "input_validation_weakness": "IVW", "direct_usage_of_shared_memory": "DUS"}
CLASSES = ("IVW", "UDO", "DUS", "ORDER")
ROLES = ("effect", "protection")
RUNS = ("run-01", "run-02", "run-03")
TFI = "tee-flow-inspector-gpt52"
SINGLE_RUN = {"T33": True}  # PKCS#11 was measured once because of its cost
MAJORITY = "TFI-GPT52"


def labels(cases):
    """Label positions used for scoring: approved defects at their approved positions, and the two
    PKCS#11 case-study labels (unreviewed) at their published positions."""
    rows = []
    for ta, case in cases.items():
        folder = BENCH / "defective" / case["case"]
        stored = json.loads((folder / "labels.json").read_text())
        working, _ = read_review(folder, stored)
        if (folder / "label_history.json").is_file():
            hashes = approval_hashes(folder, BENCH / case["normal"], labels=working)
            status = defect_statuses(working, hashes, defect_versions(working, hashes))
        else:
            status = {d["id"]: "unreviewed" for d in stored["defects"]}
        for published, reviewed in zip(stored["defects"], working["defects"], strict=True):
            did = published["id"]
            if status[did] == "approved":
                source = reviewed
            elif status[did] == "unreviewed" and published.get("order_example"):
                source = published
            else:
                continue
            for target in source["detector_targets"]:
                rows.append(dict(ta_id=ta, case_id=case["case"], normal=case["normal"].split("/")[-1], defect_id=did,
                                 class_id=published["class"], review=status[did], role=target["role"], path=target["path"],
                                 first_line=target["lines"][0], last_line=target["lines"][1], function=target["function"]))
    return rows


def diting(ta):
    path = RESULTS / "diting-codeql-semgrep/cases" / ta / "diting.txt"
    if not path.is_file():
        return None
    lines, reports = path.read_text().splitlines(), []
    assert len(lines) == 6, path
    for i, (category, title) in enumerate(DITING_TITLES.items()):
        entries = ast.literal_eval(lines[2 * i + 1])
        assert lines[2 * i] == f"{title}: {len(entries)}", path
        for n, item in enumerate(entries, 1):
            file, a, _, b, _ = re.search(r"file://([^:\n]+):(\d+):(\d+):(\d+):(\d+)$", item).groups()
            reports.append(dict(ref=f"{category}-{n}", cls=category, path=file.split(f"/sources/{ta}/")[-1],
                                first=int(a), last=int(b), rule=category))
    return reports


def codeql(ta):
    path = RESULTS / "diting-codeql-semgrep/cases" / ta / "codeql.sarif.gz"
    if not path.is_file():
        return None
    reports = []
    for n, result in enumerate(json.loads(gzip.decompress(path.read_bytes()))["runs"][0]["results"], 1):
        place = result["locations"][0]["physicalLocation"]
        region = place["region"]
        reports.append(dict(ref=f"R{n}", cls=None, path=unquote(place["artifactLocation"]["uri"]),
                            first=region["startLine"], last=region.get("endLine", region["startLine"]), rule=result["ruleId"]))
    return reports


def semgrep(ta):
    path = RESULTS / "diting-codeql-semgrep/cases" / ta / "semgrep.json"
    if not path.is_file():
        return None
    return [dict(ref=f"R{n}", cls=None, path=r["path"], first=r["start"]["line"], last=r["end"]["line"], rule=r["check_id"])
            for n, r in enumerate(json.loads(path.read_text())["results"], 1)]


def source_path(ta, name, files):
    """Reports give either the absolute input path or a path relative to the TA's ta/ directory."""
    raw = PurePosixPath(name or "")
    if not name or ".." in raw.parts:
        return None
    if raw.is_absolute():
        project = PurePosixPath("/inputs") / ta
        rel = raw.relative_to(project).as_posix() if raw.is_relative_to(project) else None
        return rel if rel in files else None
    rel = (PurePosixPath("ta") / raw).as_posix()
    return rel if rel in files else None


def tee_flow(ta, run):
    root = RESULTS / TFI / ("pkcs11-T33" if ta in SINGLE_RUN else f"{run}/cases/{ta}")
    if ta in SINGLE_RUN and run != RUNS[0]:
        return None
    done = [p for p in sorted(root.glob("attempt-*/run.json")) if json.loads(p.read_text())["status"] == "completed"]
    if not done:
        return None
    native = done[-1].parent / "outputs/results_1"
    files = json.loads((RESULTS / TFI / "inputs.json").read_text())[ta]["files"]
    coverage = json.loads((done[-1].parent / "coverage.json").read_text())
    assert coverage["passed"] and coverage["expected_flow_count"] == coverage["recorded_flow_count"], native
    reports = []
    for f in json.loads((native / "ta_vulnerabilities.json").read_text())["vulnerabilities"]:
        path = source_path(ta, f.get("file"), files)
        line = f.get("line") if type(f.get("line")) is int else None
        reports.append(dict(ref=f["vulnerability_id"], cls=LLM_CLASSES.get(f["primary_rule_id"]), path=path,
                            first=line, last=line, rule=f["primary_rule_id"]))
    return reports


def majority(ta):
    runs = [tee_flow(ta, run) for run in RUNS]
    done = [r for r in runs if r is not None]
    if SINGLE_RUN.get(ta) and runs[0] is not None:
        return runs[0]
    if len(done) != len(RUNS):
        return None
    votes = defaultdict(list)
    for reports in done:
        for key in {(r["path"], r["first"]) for r in reports if r["path"] and r["first"] is not None}:
            votes[key].append(Counter(r["cls"] for r in reports if (r["path"], r["first"]) == key).most_common(1)[0][0])
    out = []
    for n, ((path, line), classes) in enumerate(sorted(k for k in votes.items() if len(k[1]) >= 2), 1):
        cls, count = Counter(classes).most_common(1)[0]
        out.append(dict(ref=f"M{n}", cls=cls if count >= 2 else None, path=path, first=line, last=line,
                        rule=f"{len(classes)}/3 runs: " + "/".join(c or "unmapped" for c in classes)))
    return out


def write(name, rows, columns=None):
    out = RESULTS / "summary" / name
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns or list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    cases = json.loads((RESULTS / "cases.json").read_text())
    targets = labels(cases)
    write("labels.csv", targets)
    methods = [("DITING-GP11", diting), ("CodeQL", codeql), ("Semgrep", semgrep)]
    methods += [(MAJORITY, majority)]
    methods += [(f"TFI-GPT52/{run}", lambda ta, run=run: tee_flow(ta, run)) for run in RUNS]
    outputs = {(m, ta): reader(ta) for m, reader in methods for ta in cases}
    locations, matches, counts = [], [], []
    for (method, ta), reports in outputs.items():
        mine = [t for t in targets if t["ta_id"] == ta]
        by_class = Counter(r["cls"] or "unmapped" for r in reports or [])
        counts.append(dict(method=method, ta_id=ta, status="completed" if reports is not None else "pending",
                           reports="" if reports is None else len(reports), **{c: by_class[c] if reports is not None else ""
                                                                               for c in ("IVW", "UDO", "DUS", "unmapped")}))
        for t in mine:
            hit = [r for r in reports or [] if r["path"] == t["path"] and r["first"] is not None
                   and r["first"] <= t["last_line"] and t["first_line"] <= r["last"]]
            comparable = method != "CodeQL" and method != "Semgrep" and t["class_id"] != "ORDER"
            same = [r for r in hit if r["cls"] == t["class_id"]]
            key = {k: t[k] for k in ("ta_id", "defect_id", "class_id", "role", "path", "first_line", "last_line")}
            locations.append(dict(key, method=method, status="completed" if reports is not None else "pending",
                                  hits="" if reports is None else len(hit),
                                  same="" if reports is None or not comparable else len(same)))
            for r in hit:
                matches.append(dict(key, method=method, report=r["ref"], report_line=r["first"],
                                    reported_class=r["cls"] or "", rule=r["rule"]))
    write("locations.csv", locations)
    write("matches.csv", matches, ["ta_id", "defect_id", "class_id", "role", "path", "first_line", "last_line",
                                    "method", "report", "report_line", "reported_class", "rule"])
    write("reports.csv", counts)

    # One row per method, class and role. TEE Flow Inspector also gets rows over the three runs.
    def tally(method, rows, hit, same):
        out = []
        for cls in CLASSES + ("all",):
            for role in ROLES:
                sel = [t for t in rows if (cls == "all" or t["class_id"] == cls) and t["role"] == role]
                if not sel:
                    continue
                done = [t for t in sel if hit(t) is not None]
                comp = [t for t in done if same(t) is not None]
                out.append(dict(method=method, class_id=cls, role=role, targets=len(sel), evaluated=len(done),
                                position_matches=sum(hit(t) for t in done), class_comparable=len(comp),
                                class_matches=sum(same(t) for t in comp)))
        return out

    table = defaultdict(dict)
    for row in locations:
        key = (row["ta_id"], row["defect_id"], row["role"], row["path"], row["first_line"])
        table[row["method"]][key] = row
    ident = lambda t: (t["ta_id"], t["defect_id"], t["role"], t["path"], t["first_line"])
    summary = []
    for method, _ in methods:
        cell = lambda t, col: None if table[method][ident(t)][col] == "" else table[method][ident(t)][col] > 0
        summary += tally(method, targets, lambda t: cell(t, "hits"), lambda t: cell(t, "same"))
    runs = [f"TFI-GPT52/{run}" for run in RUNS]
    write("by-class.csv", summary)
    stability = []
    for t in targets:
        values = {m.split("/")[1]: table[m][ident(t)] for m in runs}
        stability.append(dict({k: t[k] for k in ("ta_id", "defect_id", "class_id", "role", "path", "first_line", "last_line")},
                              **{f"{run}_hits": v["hits"] for run, v in values.items()},
                              **{f"{run}_same": v["same"] for run, v in values.items()}))
    write("tee-flow-runs.csv", stability)
    # The compact table: detections, position matches, and correct detections per class and role.
    totals = Counter()
    for row in counts:
        if row["reports"] != "":
            totals[row["method"]] += row["reports"]
    by = {(r["method"], r["class_id"], r["role"]): r for r in summary}
    names = [("DITING-GP11", "DITING（GP 1.1互換）"), ("CodeQL", "標準CodeQL"), ("Semgrep", "Semgrep CE"),
             (MAJORITY, "TEE Flow Inspector＋GPT-5.2")]
    head = ["手法", "検出数", "位置一致（保護行）", "位置一致（影響行）"]
    head += [f"{c}（{'保護行' if role == 'protection' else '影響行'}）" for c in CLASSES for role in ("protection", "effect")]
    lines = ["| " + " | ".join(head) + " |", "| --- |" + " ---: |" * (len(head) - 1)]
    for method, label in names:
        cells = [label, str(totals[method])]
        for role in ("protection", "effect"):
            r = by[method, "all", role]
            cells.append(f"{r['position_matches']}/{r['targets']}" if r["evaluated"] == r["targets"] else "未完了")
        for cls in CLASSES:
            for role in ("protection", "effect"):
                r = by.get((method, cls, role))
                if r is None:
                    cells.append("—")
                elif r["evaluated"] != r["targets"]:
                    cells.append("未完了")
                else:
                    classed = cls != "ORDER" and method not in ("CodeQL", "Semgrep")
                    cells.append(f"{r['class_matches'] if classed else r['position_matches']}/{r['targets']}")
        lines.append("| " + " | ".join(cells) + " |")
    (RESULTS / "summary/summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
