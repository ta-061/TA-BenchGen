"""Build a relational snapshot and its Excel/CSV projections from saved measurements."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

import label_counts as source

HERE = Path(__file__).resolve().parent
OUT = source.RESULTS / "outputs/label-comparison"
DATABASE = "benchmark-results.db"
WORKBOOK = "TA別検知結果.xlsx"
METHODS = {
    "DITING": ("DITING 公開版", "results/2026-11-21/diting"),
    "DITING-GP11": ("DITING 1.1互換版", "results/diting-gp11/diting"),
    "CodeQL": ("標準CodeQL", "results/2026-11-21/codeql"),
    "Semgrep": ("Semgrep CE", "results/2026-11-21/semgrep"),
    "TFI-Qwen": ("TEE Flow Inspector＋Qwen", "results/llm-e12-qwen/cases"),
}


def populate(db, data):
    manifest = source.load_json(source.STATIC / "inputs.json")
    commit = source.load_json(source.STATIC / "environment.json")["git_commit"]
    db.execute("INSERT INTO snapshot VALUES (1,?,?)", (commit, data["llm_status"]["updated_utc"]))
    for i, m in enumerate(data["methods"], 1):
        name, directory = METHODS[m]
        db.execute("INSERT INTO method VALUES (?,?,?,?)", (m, name, i, directory))
    db.executemany("INSERT INTO defect_class VALUES (?,?)",
                   [(c, i) for i, c in enumerate(data["classes"], 1) if c != "unmapped"])
    db.executemany("INSERT INTO method_class VALUES (?,?)",
                   [(m, c) for m in data["methods"] for c in sorted(source.MAPPED[m])])
    # The extractor emits a target projection per method. Store each benchmark target once.
    targets = [t for t in data["targets"] if t["method"] == data["methods"][0]]
    decisions = {(t["id"], t["defect"]): t["decision"] for t in targets}
    # Insert controls first to satisfy self-references even when a case is archived.
    for c in sorted(data["cases"], key=lambda c: (c["review"] != "normal", c["id"])):
        ta, normal = c["id"], c["review"] == "normal"
        db.execute("INSERT INTO ta VALUES (?,?,?,?,?,?,?,?)",
                   (ta, None if normal else c["normal_id"], Path(c["original_source"]).name if normal else None,
                    c["case_id"] or None, c["scope"], c["review"], c["original_source"], c["benchmark_source"]))
        db.executemany("INSERT INTO source_file VALUES (?,?,?)",
                       [(ta, name, digest) for name, digest in sorted(manifest[ta]["files"].items())])
        if not normal:
            labels = source.load_json(source.REPO / c["benchmark_source"] / "../labels.json")
            db.executemany("INSERT INTO defect VALUES (?,?,?,?,?,?)", [
                (ta, d["id"], d["class"], decisions[ta, d["id"]], d.get("order_example"), d["reason"])
                for d in labels["defects"]])
    for t in targets:
        db.execute("""INSERT INTO label_target
                   (ta_id,defect_id,path,first_line,last_line,role,function_name,is_public,is_approved)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                   (t["id"], t["defect"], t["path"], t["first"], t["last"], t["role"],
                    t["function"], t["public"], t["approved"]))
    db.executemany("INSERT INTO analysis_run VALUES (?,?,?,?)",
                   [(r["id"], r["method"], r["status"], r["output"]) for r in data["counts"]])
    rule_map = {m: {v: k for k, v in source.TITLES.items()} for m in ("DITING", "DITING-GP11")}
    rule_map["TFI-Qwen"] = source.LLM_CLASSES
    rules = {(r["method"], name) for r in data["reports"] for name in r["rule_ids"]}
    db.executemany("INSERT INTO native_rule VALUES (?,?,?)",
                   [(m, name, rule_map.get(m, {}).get(name)) for m, name in sorted(rules)])
    for r in data["reports"]:
        key = (r["id"], r["method"], r["ref"])
        db.execute("INSERT INTO report VALUES (?,?,?)", key)
        db.executemany("INSERT INTO report_rule VALUES (?,?,?,?,?)",
                       [(*key, name, name == r["rule"]) for name in r["rule_ids"]])
        db.executemany("INSERT INTO report_location VALUES (?,?,?,?,?,?,?,?,?)",
                       [(*key, i, *loc) for i, loc in enumerate(r["locations"], 1)])


def verify_and_project(db, data):
    source.check(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity check")
    source.check(not db.execute("PRAGMA foreign_key_check").fetchall(), "Broken foreign key")
    totals = db.execute("""SELECT (SELECT count(*) FROM report), (SELECT count(*) FROM v_report),
                          (SELECT count(*) FROM report_location WHERE ordinal = 1)""").fetchone()
    source.check(all(v == len(data["reports"]) for v in totals), "Missing report, primary rule or location")
    catalog = {r["ta_id"]: r for r in db.execute("SELECT * FROM v_ta")}
    source.check(all(catalog[c["id"]]["display_name"] == c["ta"] for c in data["cases"]), "TA name mismatch")
    expected = {(r["id"], r["method"]): r for r in data["counts"]}
    all_runs = {(r["ta_id"], r["method_id"]): r for r in db.execute("SELECT * FROM v_ta_method")}
    source.check(expected.keys() == all_runs.keys(), "Missing TA/method pair")
    classified = {(r["ta_id"], r["method_id"], r["class_id"]): r
                  for r in db.execute("SELECT * FROM v_ta_method_class")}
    flat = []
    for key, previous in expected.items():
        case, run = catalog[key[0]], all_runs[key]
        r = dict(id=key[0], ta=case["display_name"], scope=case["scope"], review=case["review"],
                 case_id=case["case_id"] or "", normal_id=case["normal_id"], original_source=case["input_path"],
                 benchmark_source=case["benchmark_path"], method=key[1], status=run["status"],
                 output=run["output_path"])
        r.update({k: run[k] for k in run.keys() if k not in ("ta_id", "method_id", "output_path")})
        for c in data["classes"]:
            group = classified.get((*key, c))
            for measure in source.COUNTS:
                r[f"{measure}_{c}"] = group[measure] if group is not None else None
        source.check(r == previous, f"SQL and raw-file counts disagree: {key}")
        flat.append(r)
    def target_key(ta, method, defect, role, path, start, end, public, approved, hits, same):
        return (ta, method, defect, role, path, start, end, bool(public), bool(approved), hits, same)
    expected_targets = {target_key(r["id"], r["method"], r["defect"], r["role"], r["path"], r["first"],
                                   r["last"], r["public"], r["approved"], r["hits"], r["same"])
                        for r in data["targets"]}
    target_results = db.execute("""SELECT ta_id, method_id, defect_id, role, path, first_line, last_line,
                                 is_public, is_approved, hits, same FROM v_target_result""")
    source.check(expected_targets == {target_key(*r) for r in target_results}, "Target matches disagree")
    return flat


def export_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def excel(stage, previews=None):
    runtime = Path(os.environ.get("TA_REPORT_NODE_RUNTIME",
                     Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"))
    node = runtime / "bin/node"
    if not (node.is_file() and (runtime / "node_modules/@oai/artifact-tool").is_dir()):
        raise RuntimeError("TA_REPORT_NODE_RUNTIME must contain bin/node and node_modules/@oai/artifact-tool")
    (stage / "node_modules").symlink_to(runtime / "node_modules", target_is_directory=True)
    script = stage / "label_workbook.mjs"
    shutil.copyfile(HERE / script.name, script)
    command = [node, script, stage / DATABASE, stage / WORKBOOK]
    if previews:
        previews.mkdir(parents=True, exist_ok=True)
        command.append(previews)
    subprocess.run(command, check=True)


def build(output, make_excel=True, previews=None):
    data = source.extract()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        stage = Path(tmp)
        db = sqlite3.connect(stage / DATABASE)
        db.row_factory = sqlite3.Row
        try:
            db.executescript((HERE / "label_schema.sql").read_text(encoding="utf-8"))
            with db:
                populate(db, data)
            wide = verify_and_project(db, data)
            lead = ["ta", "id", "scope", "review", "normal_id", "method", "status", *source.COUNTS]
            export_csv(stage / "ta-method.csv", wide, lead + [k for k in data["counts"][0] if k not in lead])
            summary = [dict(r) for r in db.execute("""SELECT s.* FROM v_method_summary s
                       JOIN method m USING (method_id) ORDER BY m.sort_order""")]
            export_csv(stage / "method-summary.csv", summary, list(summary[0]))
        finally:
            db.close()
        artifacts = [DATABASE, "ta-method.csv", "method-summary.csv"]
        if make_excel:
            excel(stage, previews)
            artifacts.append(WORKBOOK)
        for name in artifacts:
            (stage / name).replace(output / name)
    print(f"{len(wide)} TA/method measurements, {len(data['reports'])} final reports. {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=OUT)
    p.add_argument("--data-only", action="store_true", help="refresh only the SQLite database and CSV exports")
    p.add_argument("--preview-dir", type=Path, help="also render worksheet previews to this directory")
    args = p.parse_args()
    build(args.output_dir.resolve(), not args.data_only, args.preview_dir)
