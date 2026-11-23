"""Run DITING against copies of the 35 databases from the baseline measurement."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent / "2026-11-21"
QUERIES = ("host", "switch", "arrayaccess", "ifstmt", "dataflow", "memory", "memflow")


def run_case(case, files, baseline_work, work, env):
    job = work / "jobs" / case
    (job / "out").mkdir(parents=True)
    database = baseline_work / "jobs" / case / "tee_example"
    if sys.platform == "darwin":
        subprocess.run(["/bin/cp", "-cR", database, job / "tee_example"], check=True)
    else:
        shutil.copytree(database, job / "tee_example")
    with ZipFile(job / "tee_example/src.zip") as archive:
        prefix = f"/sources/{case}/"
        entries = {n.split(prefix)[1]: n for n in archive.namelist() if prefix in n}
        for path, digest in files.items():
            if path.endswith(".c") and sha256(archive.read(entries[path])).hexdigest() != digest:
                raise ValueError(f"Database source differs: {case}/{path}")

    trace = job / "queries.jsonl"
    env = dict(env, DITING_TRACE=str(trace))
    argv = [sys.executable, str(work / "real_world_analysis.py")]
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    with (job / "diting.txt").open("wb") as output, (job / "diting.log").open("wb") as log:
        proc = subprocess.run(argv, cwd=job, env=env, stdout=output, stderr=log)
    record = dict(argv=argv, cwd=str(job), started_utc=started,
                  seconds=round(time.monotonic() - start, 3), exit_code=proc.returncode)
    (job / "driver.json").write_text(json.dumps(record) + "\n")
    proc.check_returncode()
    with (job / "out/memflow.out").open("wb") as out, (job / "memflow.log").open("wb") as log:
        subprocess.run(["codeql", "query", "run", "../../query/memflow.ql", "--database=tee_example"],
                       cwd=job, env=env, stdout=out, stderr=log, check=True)
    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    if tuple(Path(c["argv"][3]).stem for c in calls) != QUERIES or any(c["exit_code"] for c in calls):
        raise RuntimeError(f"Check {trace} for missing or failed queries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-work", type=Path, default=Path("/private/tmp/tabenchgen-static-4fc3ae9"))
    parser.add_argument("--diting", type=Path, default=HERE.parents[2] / "PartitioningE-in-TEE")
    parser.add_argument("--work", type=Path, help="New working directory (default: a temporary directory)")
    args = parser.parse_args()
    baseline_work = args.baseline_work.resolve()
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="diting-gp11-")).resolve()
    if args.work:
        work.mkdir(parents=True)
    print(f"Working directory: {work}", flush=True)
    manifest = json.loads((BASELINE / "inputs.json").read_text())
    if json.loads((baseline_work / "inputs.json").read_text()) != manifest:
        raise ValueError("The database manifest differs from the baseline.")
    (work / "query").mkdir()
    for name in QUERIES:
        shutil.copyfile(args.diting / "query" / f"{name}.ql", work / "query" / f"{name}.ql")
    shutil.copyfile(baseline_work / "query/qlpack.yml", work / "query/qlpack.yml")
    shutil.copyfile(args.diting / "real_world_analysis.py", work / "real_world_analysis.py")
    (work / "bin").mkdir()
    shim = work / "bin/codeql"
    shutil.copyfile(BASELINE / "replay/trace-codeql.py", shim)
    shim.chmod(0o755)
    cli = (baseline_work / "deps/codeql/codeql").resolve(strict=True)
    cache = (baseline_work / "deps/query-cache").resolve(strict=True)
    env = dict(os.environ, CODEQL_DIST=str(cli.parent), DITING_CLI=str(cli), DITING_CACHE=str(cache),
               PATH=str(shim.parent) + os.pathsep + os.environ["PATH"])
    version = subprocess.check_output([cli, "version", "--format=json"], env=env, text=True)
    run_info = dict(diting_base=subprocess.check_output(["git", "-C", args.diting, "rev-parse", "HEAD"],
                                                        text=True).strip(),
                    codeql=json.loads(version)["version"], python=platform.python_version(),
                    system=platform.system(), release=platform.release(), arch=platform.machine(),
                    jobs=4, threads_per_query=2, ram_per_query_mb=2048)
    (work / "environment.json").write_text(json.dumps(run_info, indent=2) + "\n")
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(run_case, case, item["files"], baseline_work, work, env): case
                 for case, item in manifest.items()}
        for completed, task in enumerate(as_completed(tasks), 1):
            task.result()
            print(f"{completed}/{len(tasks)} {tasks[task]}", flush=True)
    subprocess.run([sys.executable, HERE / "compare.py", work], check=True)


if __name__ == "__main__":
    main()
