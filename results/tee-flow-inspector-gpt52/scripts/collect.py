#!/usr/bin/env python3
"""Write runs.csv: per repetition, the numbers of sinks, candidate flows and reports, and the API usage."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICE = dict(input=1.75, cached=0.175, output=14.0)  # USD per million tokens, gpt-5.2 standard
KEYS = ("live_responses", "input_tokens", "cached_input_tokens", "output_tokens")


def main():
    rows = []
    groups = [(p.name, sorted(p.glob("cases/*/attempt-*/run.json"))) for p in sorted(ROOT.glob("run-*"))]
    groups.append(("pkcs11-T33", sorted((ROOT / "pkcs11-T33").glob("attempt-*/run.json"))))
    for name, records in groups:
        last = {}
        for path in records:
            record = json.loads(path.read_text())
            last[record["id"]] = record
        done = [r for r in last.values() if r["status"] == "completed"]
        row = dict(run=name, tas=len(last), completed=len(done), sinks=sum(r.get("sinks") or 0 for r in done),
                   flows=sum(r["flows"] for r in done), findings=sum(r["findings"] for r in done))
        for key in KEYS:
            row[key] = sum(json.loads(p.read_text()).get("usage", {}).get(key, 0) for p in records)
        row["standard_usd"] = round(((row["input_tokens"] - row["cached_input_tokens"]) * PRICE["input"]
                                     + row["cached_input_tokens"] * PRICE["cached"]
                                     + row["output_tokens"] * PRICE["output"]) / 1e6, 2)
        rows.append(row)
        print(row)
    with (ROOT / "runs.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
