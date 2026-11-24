#!/usr/bin/env python3
"""Run DITING (with the GP 1.1 type-name patch), standard CodeQL and Semgrep on the defective TAs.

    python3.11 results/diting-codeql-semgrep/scripts/run.py WORK [T18 ...] [--jobs 4]

Environment: TA_MEASURE_TOOLS holds codeql/, devkit/include, client/, venv/bin/semgrep and
semgrep-c.yaml; DITING_ROOT is a clean PartitioningE-in-TEE checkout at cb72e886; TA_CC is the
clang used for the TA sources. Each TA is copied without labels, compiled once into a CodeQL
database, and analyzed with the same commands as the 2026-11-21 measurement.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent
RESULTS = STATIC.parent
BENCH = RESULTS.parent / "benchmark"
PATCH = "diting-gp11-typename.patch"
QUERIES = ("host", "switch", "arrayaccess", "ifstmt", "dataflow", "memory", "memflow")
PATCHED = {"arrayaccess.ql": "392765cba3f2a4fce8ee986de379faeefe00ed7db7474eae6b6ede45556a5eec",
           "dataflow.ql": "8cb95b3df3b07c5b152e23eb0799297fc18f91b349fcfe1042a00499032b4de9",
           "host.ql": "d548fcb1632a9e3664f02008588f94f1c18387e1ee4a83daeb7b9341a07119f3",
           "ifstmt.ql": "7e1689aa5c9e66fbe6950dd20727f3b905c5552c490d78c6d3624ae40cda5254",
           "memflow.ql": "8fe1f940902f1f84592631d9e3c5fd622aa672a11fa5d3a7f247edfdd7bfc781",
           "memory.ql": "c45582543f773e7cc8ce1f4f8aa0da4a50d285fc33cbc9aa926ae460ad473b5f",
           "switch.ql": "8f303de92805b9444af6c2106633736983704cf2a790c68ccb9111589780d3d1"}
RULES_SHA = "dd64d05287cb249e51b8869d9bb2dfc19906ebffd49a62704656dd5a015bed79"


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare(work, tools, diting):
    deps = work / "deps"
    deps.mkdir(parents=True)
    for name, target in [("codeql", tools / "codeql"), ("devkit", tools / "devkit"), ("client", tools / "client"),
                         ("sem-bin", tools / "venv/bin"), ("rules.yaml", tools / "semgrep-c.yaml")]:
        (deps / name).symlink_to(target.resolve(strict=True))
    (work / "cache").mkdir()
    if digest(deps / "rules.yaml") != RULES_SHA:
        raise ValueError("The Semgrep C profile differs from the recorded two-rule snapshot.")
    shutil.copyfile(STATIC / "optee-conf.h", deps / "conf.h")
    (deps / "log-level.h").write_text("#undef CFG_TEE_TA_LOG_LEVEL\n#define CFG_TEE_TA_LOG_LEVEL 4\n")
    if subprocess.check_output(["git", "-C", diting, "status", "--porcelain", "query", "real_world_analysis.py"]):
        raise ValueError("DITING_ROOT must be an unmodified checkout")
    base = subprocess.check_output(["git", "-C", diting, "rev-parse", "HEAD"], text=True).strip()
    query = work / "query"
    query.mkdir()
    for name in QUERIES:
        shutil.copyfile(diting / "query" / f"{name}.ql", query / f"{name}.ql")
    shutil.copyfile(diting / "real_world_analysis.py", work / "real_world_analysis.py")
    subprocess.run(["patch", "-s", "-p1", "-i", str(STATIC / PATCH)], cwd=work, check=True)
    for name, expected in PATCHED.items():
        if digest(query / name) != expected:
            raise ValueError(f"Patched query differs from the recorded one: {name}")
    (query / "qlpack.yml").write_text("name: getting-started/tee-bad-partitioning\nversion: 0.0.0\n"
                                      "dependencies:\n  codeql/cpp-all: 5.5.0\n")
    (work / "bin").mkdir()
    shim = work / "bin/codeql"
    shutil.copyfile(HERE / "trace-codeql.py", shim)
    shim.chmod(0o755)
    shutil.copyfile(HERE / "compile.py", work / "compile.py")
    return base


def stage(work, key, case, cc, host_cc):
    original = BENCH / case["source"]
    src, job, deps = work / "sources" / key, work / "jobs" / key, work / "deps"
    (job / "out").mkdir(parents=True)
    (job / "objects").mkdir()
    files = {}
    for part in ("ta", "host", "include"):
        for file in sorted((original / part).rglob("*")):
            if file.suffix in {".c", ".h", ".s", ".S"} and file.is_file():
                dest = src / file.relative_to(original)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, dest)
                files[file.relative_to(original).as_posix()] = digest(dest)
    compat = bool(re.search(r"(?m)^CFG_TA_OPTEE_CORE_API_COMPAT_1_1\s*=\s*y\s*$", (original / "ta/Makefile").read_text()))
    commands = []
    for side in ("ta", "host"):
        for file in sorted((src / side).rglob("*.c")):
            includes = [src / "ta/include", src / "include"]
            if side == "ta":
                argv = [cc, "--target=aarch64-none-elf", "-ffreestanding", "-fno-builtin",
                        "-include", deps / "conf.h", "-include", deps / "log-level.h"]
                if compat:
                    argv.append("-D__OPTEE_CORE_API_COMPAT_1_1=1")
                includes += [src / "ta", src / "ta/src", deps / "devkit/include"]
            else:
                argv = [host_cc]
                includes += [src / "host/libckteec/include", src / "host/libckteec/src", deps / "client"]
            for folder in includes:
                if folder.is_dir():
                    argv.extend(["-I", folder])
            argv.extend(["-c", file.relative_to(src), "-o", job / "objects" / f"{len(commands)}.o"])
            commands.append(list(map(str, argv)))
    save(job / "compile.json", commands)
    return dict(case=case["case"], source=case["source"], files=files, gp_1_1=compat,
                ta_c_files=sum(c[1].startswith("--target") for c in commands), host_c_files=sum(not c[1].startswith("--target") for c in commands))


def run_case(work, key):
    job, src, deps = work / "jobs" / key, work / "sources" / key, work / "deps"
    tool = (deps / "codeql").resolve() / "codeql"
    os.environ["CODEQL_DIST"] = str(tool.parent)  # the bundle is reached through a symlink
    suite = deps / "codeql/qlpacks/codeql/cpp-queries/1.4.7/codeql-suites/cpp-security-extended.qls"
    limits = [f"--common-caches={work / 'cache'}", "--threads=2", "--ram=2048"]
    logs = job / "logs"
    logs.mkdir()
    records = []

    def execute(name, argv, cwd, env=None, stdout=None):
        argv = list(map(str, argv))
        started = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()
        with (logs / f"{name}.log").open("wb") as log:
            if stdout is None:
                proc = subprocess.run(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            else:
                with stdout.open("wb") as output:
                    proc = subprocess.run(argv, cwd=cwd, env=env, stdout=output, stderr=log)
        records.append({"stage": name, "cwd": str(cwd), "argv": argv, "started_utc": started,
                        "seconds": round(time.monotonic() - start, 3), "exit_code": proc.returncode})
        save(job / "commands.json", records)
        return proc.returncode

    env = os.environ.copy()
    env.pop("SEMGREP_APP_TOKEN", None)
    env.update(PATH=str(deps / "sem-bin") + os.pathsep + env["PATH"], SEMGREP_SETTINGS_FILE=str(job / "semgrep-settings.yml"),
               SEMGREP_SEND_METRICS="off", SEMGREP_ENABLE_VERSION_CHECK="0")
    for attempt in ("semgrep", "semgrep-retry"):
        # The engine is occasionally killed under memory pressure; a killed scan is repeated once and both are recorded.
        if execute(attempt, [deps / "sem-bin/semgrep", "scan", "--config", deps / "rules.yaml", "--metrics=off",
                             "--disable-version-check", "--oss-only", "--no-git-ignore", "--no-rewrite-rule-ids",
                             "--jobs=2", "--json", "--output", job / "semgrep.json", "."], src, env) == 0:
            break
    db = job / "tee_example"
    build = shlex.join([sys.executable, str(work / "compile.py"), str(job / "compile.json")])
    if execute("database-create", [tool, "database", "create", db, "--language=cpp", "--source-root", src,
                                   "--command", build, *limits], src) == 0:
        env = dict(os.environ, PATH=str(work / "bin") + os.pathsep + os.environ["PATH"],
                   DITING_CLI=str(tool), DITING_CACHE=str(work / "cache"), DITING_TRACE=str(job / "query-calls.jsonl"))
        execute("diting", [sys.executable, work / "real_world_analysis.py"], job, env, stdout=job / "diting.txt")
        execute("diting-memflow", [tool, "query", "run", work / "query/memflow.ql", "--database", db, *limits],
                job, stdout=job / "out/memflow.out")
        execute("codeql", [tool, "database", "analyze", db, suite, "--format=sarif-latest",
                           "--output", job / "codeql.sarif", *limits], src)
    print(key, {r["stage"]: r["exit_code"] for r in records}, flush=True)
    return records


def publish(work, key, python, tools):
    """Copy the reports into results/diting-codeql-semgrep/cases/, with the scratch and tool paths written as ${WORK} and ${TOOLS}."""
    job, out = work / "jobs" / key, STATIC / "cases" / key
    out.mkdir(parents=True, exist_ok=True)
    def neutral(text):
        return text.replace(str(work), "${WORK}").replace(python, "${PYTHON}").replace(str(tools), "${TOOLS}")
    (out / "diting.txt").write_text(neutral((job / "diting.txt").read_text()))
    if (job / "codeql.sarif").is_file():
        with gzip.GzipFile(out / "codeql.sarif.gz", "wb", mtime=0) as f:
            f.write(neutral((job / "codeql.sarif").read_text()).encode())
    (out / "semgrep.json").write_text(neutral((job / "semgrep.json").read_text()))
    tables = out / "diting-queries"
    tables.mkdir(exist_ok=True)
    for file in sorted((job / "out").iterdir()):
        (tables / file.name).write_text(neutral(file.read_text()))
    calls = [json.loads(line) for line in (job / "query-calls.jsonl").read_text().splitlines()]
    commands = json.loads((job / "commands.json").read_text()) + [dict(c, stage="diting-query") for c in calls]
    commands += [dict(stage="compile-plan", argv=argv) for argv in json.loads((job / "compile.json").read_text())]
    (out / "commands.json").write_text(neutral(json.dumps(commands, indent=2)) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("work", type=Path, help="new scratch directory for databases and raw results")
    parser.add_argument("ids", nargs="*", help="TA IDs (default: all in results/cases.json)")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        parser.error("Use an empty scratch directory.")
    tools = Path(os.environ["TA_MEASURE_TOOLS"]).resolve()
    diting = Path(os.environ.get("DITING_ROOT", RESULTS.parents[1] / "PartitioningE-in-TEE")).resolve()
    cc = os.environ.get("TA_CC", "/usr/lib/llvm-18/bin/clang")
    host_cc = os.environ.get("HOST_CC", "/usr/bin/clang")
    cases = json.loads((RESULTS / "cases.json").read_text())
    ids = args.ids or list(cases)
    base = prepare(work, tools, diting)
    inputs = {key: stage(work, key, cases[key], cc, host_cc) for key in ids}
    order = sorted(ids, key=lambda k: -len(inputs[k]["files"]))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = dict(zip(order, pool.map(lambda key: run_case(work, key), order)))
    failed = [k for k, rows in records.items() if len({r["stage"] for r in rows if r["exit_code"] == 0}) != 5]
    if failed:
        raise SystemExit(f"Failed stages: {failed}; see {work}/jobs/*/logs")
    for key in ids:
        publish(work, key, sys.executable, tools)
    version = lambda argv: subprocess.check_output(argv, text=True).splitlines()[0]
    tool = work / "deps/codeql/codeql"
    environment = dict(
        measured_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        platform=platform.system(), platform_release=platform.release(), arch=platform.machine(),
        python=platform.python_version(), jobs=args.jobs, threads_per_query=2, ram_per_query_mb=2048,
        clang_ta=version([cc, "--version"]), clang_host=version([host_cc, "--version"]),
        codeql=json.loads(subprocess.check_output([tool, "version", "--format=json"], text=True))["version"],
        cpp_all="5.5.0", cpp_queries="1.4.7", suite="cpp-security-extended.qls",
        diting=dict(base=base, patch=PATCH, patch_sha256=digest(STATIC / PATCH),
                    files_sha256={**{n: digest(work / "query" / n) for n in sorted(PATCHED)},
                                  "qlpack.yml": digest(work / "query/qlpack.yml"),
                                  "real_world_analysis.py": digest(work / "real_world_analysis.py")}),
        semgrep=dict(version=subprocess.check_output([work / "deps/sem-bin/semgrep", "--disable-version-check", "--version"],
                                                     text=True).strip(), rules_sha256=RULES_SHA),
        optee_conf_sha256=digest(STATIC / "optee-conf.h"))
    existing = json.loads((STATIC / "inputs.json").read_text()) if (STATIC / "inputs.json").is_file() else {}
    existing.update(inputs)
    save(STATIC / "inputs.json", dict(sorted(existing.items())))
    save(STATIC / "environment.json", environment)
    print("Published:", STATIC / "cases")


if __name__ == "__main__":
    main()
