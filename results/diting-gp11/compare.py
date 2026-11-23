"""Compare a completed DITING run with the published baseline; write work/report/."""

import ast
from collections import Counter
import csv
from difflib import SequenceMatcher
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
import tarfile
from zipfile import ZipFile


BASELINE = Path(__file__).resolve().parent.parent / "2026-11-21"
OUTPUTS = {"host": "params_type", "switch": "func_id", "arrayaccess": "arrayaccess",
           "ifstmt": "ifstmt", "dataflow": "dataflow", "memory": "unencrypt", "memflow": "memflow"}
TITLES = {"UDO": "Unencrypted Data Output", "IVW": "Input Validation Weakness",
          "DUS": "Shared Memory Overwrite"}


def table_rows(text):
    header, separator, *rows = text.splitlines()
    if not header.startswith("|") or not separator.startswith("+") or any(not r.startswith("|") for r in rows):
        raise ValueError("Incomplete CodeQL result table")
    return rows


def linked_flows(tables):
    # Use the command, handler, and parameter tests from real_world_analysis.py.
    commands = {r.replace(" ", "").split("|")[1] for r in tables["host"]}
    handlers = {}
    for row in tables["switch"]:
        cells = row.replace(" ", "").split("|")
        handlers[cells[2]] = cells[1]
    current = ""
    count = 0
    for row in tables["dataflow"]:
        cells = row.replace(" ", "").split("|")
        current = handlers.get("callto" + cells[5], current)
        if current in commands and cells[1].isdigit():
            count += 1
    return count


def warnings(text, case):
    lines = text.splitlines()
    if len(lines) != 2 * len(TITLES):
        raise ValueError(f"Incomplete DITING output: {case}")
    reports = Counter()
    for i, (category, title) in enumerate(TITLES.items()):
        heading, values = lines[2 * i : 2 * i + 2]
        entries = ast.literal_eval(values)
        if heading != f"{title}: {len(entries)}":
            raise ValueError(f"Warning total differs from list: {case}/{category}")
        for item in entries:
            location = re.search(r"file://([^:\n]+):(\d+):(\d+):(\d+):(\d+)$", item)
            if not location:
                raise ValueError(f"Unrecognized DITING location: {item}")
            path, *bounds = location.groups()
            path = path.split(f"/sources/{case}/")[-1]
            reports[(category, path, *map(int, bounds))] += 1
    return reports


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def control_matches(work, case, normal, path, hits):
    def source_lines(key):
        with ZipFile(work / "jobs" / key / "tee_example/src.zip") as archive:
            name, = (n for n in archive.namelist() if n.endswith(f"/sources/{key}/{path}"))
            return archive.read(name).splitlines()

    matcher = SequenceMatcher(a=source_lines(case), b=source_lines(normal), autojunk=False)
    mapped = {a + i + 1: b + i + 1 for a, b, size in matcher.get_matching_blocks() for i in range(size)}
    control = warnings((work / "jobs" / normal / "diting.txt").read_text(), normal)
    total = 0
    for (category, _, first, col, last, last_col), count in hits.items():
        start = mapped.get(first)
        if start is not None and all(mapped.get(i) == start + i - first for i in range(first, last + 1)):
            location = (category, path, start, col, mapped[last], last_col)
            total += min(count, control[location])
    return total


def report_case(case, work, report, records):
    job = work / "jobs" / case
    before, after = {}, {}
    with tarfile.open(BASELINE / "logs" / f"{case}.tar.gz") as old:
        for query, name in OUTPUTS.items():
            filename = f"out/{name}.out"
            before[query] = table_rows(old.extractfile(filename).read().decode())
            after[query] = table_rows((job / filename).read_text())
    driver = json.loads((job / "driver.json").read_text())
    queries = [json.loads(line) for line in (job / "queries.jsonl").read_text().splitlines()]
    query_names = [Path(record["argv"][3]).stem for record in queries]
    if query_names != list(OUTPUTS) or any(r["exit_code"] for r in [driver, *queries]):
        raise ValueError(f"Missing or failed command: {case}")
    cli, cache = queries[0]["argv"][0], queries[0]["argv"][-3].removeprefix("--common-caches=")

    def portable(text):
        for path, name in ((str(work), "${WORK}"), (cli, "${CODEQL}"), (cache, "${QUERY_CACHE}"),
                           (driver["argv"][0], "${PYTHON}"), (str(Path.home()), "${HOME}")):
            text = text.replace(path, name)
        return text

    for stage, record in zip(["diting", *OUTPUTS], [driver, *queries], strict=True):
        records.append(dict(id=case, stage=stage, **json.loads(portable(json.dumps(record)))))
    with tarfile.open(report / "logs" / f"{case}.tar.gz", "w:gz") as archive:
        paths = [*(job / "out").glob("*.out"), job / "diting.log", job / "memflow.log"]
        for path in sorted(paths):
            data = portable(path.read_text()).encode()
            info = tarfile.TarInfo(path.relative_to(job).as_posix())
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    text = (job / "diting.txt").read_text()
    (report / "diting" / f"{case}.txt").write_text(portable(text))
    old_warnings = warnings((BASELINE / "diting" / f"{case}.txt").read_text(), case)
    new_warnings = warnings(text, case)
    return before, after, old_warnings, new_warnings


def compare(work):
    report = work / "report"
    (report / "diting").mkdir(parents=True, exist_ok=True)
    (report / "logs").mkdir(exist_ok=True)
    inputs = json.loads((BASELINE / "inputs.json").read_text())
    labels = read_csv(BASELINE / "locations.csv")
    cases, records = [], []
    for original in read_csv(BASELINE / "cases.csv"):
        case = original["id"]
        row = {k: original[k] for k in ("id", "source", "cohort", "normal_id")}
        row["normal_source"] = inputs[row["normal_id"]]["source"]
        row["gp_1_1"] = int(inputs[case]["gp_1_1"])
        before, after, old_warnings, new_warnings = report_case(case, work, report, records)
        for query in OUTPUTS:
            row[f"{query}_before"] = len(before[query])
            row[f"{query}_after"] = len(after[query])
        for suffix, tables, alerts in (("before", before, old_warnings), ("after", after, new_warnings)):
            row[f"linked_{suffix}"] = linked_flows(tables)
            row[f"warnings_{suffix}"] = alerts.total()
            for category in TITLES:
                row[f"{category}_{suffix}"] = sum(n for (c, *_), n in alerts.items() if c == category)
        for key in TITLES:
            if row[f"{key}_before"] != int(original[f"diting_{key}"]):
                raise ValueError(f"Baseline warning count mismatch: {case}/{key}")
        if row["linked_before"] != int(original["diting_linked_rows"]):
            raise ValueError(f"Baseline linked flow count mismatch: {case}")
        row["warnings_added"] = (new_warnings - old_warnings).total()
        row["warnings_removed"] = (old_warnings - new_warnings).total()
        cases.append(row)
        for label in (item for item in labels if item["id"] == case):
            first, last = int(label["first_line"]), int(label["last_line"])
            matching_after = Counter()
            for suffix, alerts in (("before", old_warnings), ("after", new_warnings)):
                hits = Counter()
                for location, n in alerts.items():
                    category, path, start, _, end, _ = location
                    if path == label["path"] and start <= last and end >= first:
                        hits[category] += n
                        if suffix == "after" and category == label["class"]:
                            matching_after[location] += n
                label[f"hits_{suffix}"] = hits.total()
                label[f"same_class_{suffix}"] = hits[label["class"]] if label["class"] in TITLES else ""
            label["same_class_also_in_normal_after"] = label["same_class_after"]
            if matching_after:
                label["same_class_also_in_normal_after"] = control_matches(
                    work, case, row["normal_id"], label["path"], matching_after)
            baseline_hits = label.pop("diting"), label.pop("diting_same_class")
            if (str(label["hits_before"]), str(label["same_class_before"])) != baseline_hits:
                raise ValueError(f"Baseline label mismatch: {label}")
            del label["codeql"], label["semgrep"]
    write_csv(report / "cases.csv", cases)
    write_csv(report / "locations.csv", labels)
    records.sort(key=lambda r: r["started_utc"])
    (report / "commands.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    environment = json.loads((work / "environment.json").read_text())
    environment["cpp_all"] = json.loads((BASELINE / "environment.json").read_text())["codeql"]["cpp_all"]
    files = [*sorted((work / "query").glob("*.ql")), work / "query/qlpack.yml", work / "real_world_analysis.py"]
    environment["sha256"] = {f.name: sha256(f.read_bytes()).hexdigest() for f in files}
    (report / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    print(f"Compared {len(cases)} TAs. Report: {report}", flush=True)


if __name__ == "__main__":
    compare(Path(sys.argv[1]).resolve())
