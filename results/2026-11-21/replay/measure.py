"""Run the three static analyzers on separate, source-only TA-BenchGen snapshots."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
BENCH = Path(os.environ["BENCHMARK_DIR"]).resolve()
QUERY_NAMES = ["host", "switch", "arrayaccess", "ifstmt", "dataflow", "memory", "memflow"]
RULES_SHA = "dd64d05287cb249e51b8869d9bb2dfc19906ebffd49a62704656dd5a015bed79"


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def file_set_digest(files):
    h = sha256()
    for name, checksum in sorted(files.items()):
        h.update(f"{checksum}  {name}\n".encode())
    return h.hexdigest()


def prepare(work):
    deps = work / "deps"
    deps.mkdir()
    for var, name in [
        ("CODEQL_DIST", "codeql"), ("LLVM_DIST", "llvm"), ("SEM_BIN", "sem-bin"),
        ("TA_DEV_KIT_DIR", "devkit"), ("TA_CONF", "conf.h"), ("TEEC_INCLUDE", "client"),
        ("DITING_ROOT", "diting"), ("SEMGREP_CONFIG", "rules.yaml"),
    ]:
        target = Path(os.environ[var]).resolve(strict=True)
        (deps / name).symlink_to(target, target_is_directory=target.is_dir())
    cache = Path(os.environ.get("QUERY_CACHE", work / "cache")).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    (deps / "query-cache").symlink_to(cache, target_is_directory=True)
    if digest(deps / "rules.yaml") != RULES_SHA:
        raise ValueError("The Semgrep C profile differs from the recorded two-rule snapshot.")
    query = work / "query"
    query.mkdir()
    for name in QUERY_NAMES:
        shutil.copyfile(deps / "diting/query" / f"{name}.ql", query / f"{name}.ql")
    (query / "qlpack.yml").write_text(
        "name: getting-started/tee-bad-partitioning\nversion: 0.0.0\n"
        "dependencies:\n  codeql/cpp-all: 5.5.0\n"
    )
    (deps / "log-level.h").write_text("#undef CFG_TEE_TA_LOG_LEVEL\n#define CFG_TEE_TA_LOG_LEVEL 4\n")
    bindir = work / "bin"
    bindir.mkdir()
    shim = bindir / "codeql"
    shutil.copyfile(HERE / "trace-codeql.py", shim)
    shim.chmod(0o755)
    sources = [p for p in sorted((BENCH / "normal").iterdir()) if (p / "ta").is_dir()]
    sources.extend(p / "source" for p in sorted((BENCH / "defective").glob("case_*")))
    entries = {}
    for number, original in enumerate(sources, 1):
        key = f"T{number:02}"
        src = work / "sources" / key
        job = work / "jobs" / key
        (job / "out").mkdir(parents=True)
        (job / "objects").mkdir()
        files = {}
        for part in ["ta", "host", "include"]:
            for file in sorted((original / part).rglob("*")):
                if file.suffix not in {".c", ".h", ".s", ".S"} or not file.is_file():
                    continue
                rel = file.relative_to(original)
                dest = src / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, dest)
                if digest(file) != digest(dest):
                    raise ValueError(f"Source copy mismatch: {rel}")
                files[rel.as_posix()] = digest(dest)
        makefile = (original / "ta/Makefile").read_text()
        compat = bool(re.search(r"(?m)^CFG_TA_OPTEE_CORE_API_COMPAT_1_1\s*=\s*y\s*$", makefile))
        commands = compile_commands(src, job, deps, compat)
        save(job / "compile.json", commands)
        entries[key] = {"source": original.relative_to(BENCH).as_posix(),
                        "files": files, "source_sha256": file_set_digest(files),
                        "gp_1_1": compat}
    save(work / "inputs.json", entries)
    return entries


def compile_commands(src, job, deps, compat):
    commands = []
    for side in ["ta", "host"]:
        for file in sorted((src / side).rglob("*.c")):
            includes = [src / "ta/include", src / "include"]
            if side == "ta":
                argv = [deps / "llvm/bin/clang", "--target=aarch64-none-elf", "-ffreestanding",
                        "-fno-builtin", "-include", deps / "conf.h", "-include", deps / "log-level.h"]
                if compat:
                    argv.append("-D__OPTEE_CORE_API_COMPAT_1_1=1")
                includes += [src / "ta", src / "ta/src", deps / "devkit/include"]
            else:
                argv = [os.environ.get("HOST_CC", "/usr/bin/clang")]
                includes += [src / "host/libckteec/include", src / "host/libckteec/src", deps / "client"]
            for folder in includes:
                if folder.is_dir():
                    argv.extend(["-I", folder])
            argv.extend(["-c", file.relative_to(src), "-o", job / "objects" / f"{len(commands)}.o"])
            commands.append(list(map(str, argv)))
    return commands


def run_case(work, key):
    job, src, deps = work / "jobs" / key, work / "sources" / key, work / "deps"
    tool = deps / "codeql/codeql"
    suite = deps / "codeql/qlpacks/codeql/cpp-queries/1.4.7/codeql-suites/cpp-security-extended.qls"
    limits = [f"--common-caches={deps / 'query-cache'}", "--threads=2", "--ram=2048"]
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
        record = {"stage": name, "cwd": str(cwd), "argv": argv, "started_utc": started,
                  "seconds": round(time.monotonic() - start, 3), "exit_code": proc.returncode}
        records.append(record)
        save(job / "commands.json", records)
        return proc.returncode

    env = os.environ.copy()
    env.pop("SEMGREP_APP_TOKEN", None)
    env.update(PATH=str(deps / "sem-bin") + os.pathsep + env["PATH"],
               SEMGREP_SETTINGS_FILE=str(job / "semgrep-settings.yml"),
               SEMGREP_SEND_METRICS="off", SEMGREP_ENABLE_VERSION_CHECK="0")
    execute("semgrep", [deps / "sem-bin/semgrep", "scan", "--config", deps / "rules.yaml",
                        "--metrics=off", "--disable-version-check", "--oss-only", "--no-git-ignore",
                        "--no-rewrite-rule-ids", "--jobs=2", "--json", "--output", job / "semgrep.json", "."],
            src, env)
    db = job / "tee_example"
    build = shlex.join([sys.executable, str(work / "compile.py"), str(job / "compile.json")])
    if execute("database-create", [tool, "database", "create", db, "--language=cpp",
                                   "--source-root", src, "--command", build, *limits], src) == 0:
        env = dict(os.environ, PATH=str(work / "bin") + os.pathsep + os.environ["PATH"],
                   DITING_CLI=str(tool), DITING_CACHE=str(deps / "query-cache"),
                   DITING_TRACE=str(job / "query-calls.jsonl"))
        execute("diting", [sys.executable, deps / "diting/real_world_analysis.py"], job, env,
                stdout=job / "diting.txt")
        execute("diting-memflow", [tool, "query", "run", work / "query/memflow.ql",
                                   "--database", db, *limits], job, stdout=job / "out/memflow.out")
        execute("codeql", [tool, "database", "analyze", db, suite, "--format=sarif-latest",
                           "--output", job / "codeql.sarif", *limits], src)
    print(key, {r["stage"]: r["exit_code"] for r in records}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path, help="new scratch directory for databases and raw results")
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        parser.error("Use an empty scratch directory to keep previous measurements intact.")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    save(work / "settings.json", {
        "jobs": args.jobs, "host_cc": os.environ.get("HOST_CC", "/usr/bin/clang"),
        "git_commit": subprocess.check_output(["git", "-C", BENCH.parent, "rev-parse", "HEAD"], text=True).strip(),
        "benchmark_tree": subprocess.check_output(["git", "-C", BENCH.parent, "rev-parse", "HEAD:benchmark"], text=True).strip(),
    })
    shutil.copyfile(HERE / "compile.py", work / "compile.py")
    entries = prepare(work)
    # Schedule the larger PKCS#11 inputs early. Each job owns its database.
    order = sorted(entries, key=lambda k: -len(entries[k]["files"]))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda key: run_case(work, key), order))


if __name__ == "__main__":
    main()
