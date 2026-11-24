"""Stage one benchmark case as a TEE Flow Inspector input (sources and compile_commands.json).

Usage: stage_input.py TA_ID benchmark/defective/case_xxx/source INPUTS_DIR
Prints the inputs.json entry. The compile arguments match the ones used for T01-T35.
"""
import hashlib
import json
from pathlib import Path
import sys


def main():
    ta, source, inputs = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    bench = next(p for p in source.resolve().parents if p.name == "benchmark")
    files = {}
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source).as_posix()
        if path.is_file() and path.suffix in (".c", ".h") and rel.split("/")[0] in ("ta", "host", "include"):
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    makefiles = "".join(p.read_text(errors="replace") for p in source.rglob("*") if p.name in ("Makefile", "sub.mk"))
    gp11 = "CFG_TA_OPTEE_CORE_API_COMPAT_1_1" in makefiles
    dest, root, commands = inputs / ta, f"/inputs/{ta}", []
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / rel).read_bytes())
        if not (rel.startswith("ta/") and rel.endswith(".c")):
            continue
        args = ["clang", "-ffreestanding", "-fno-builtin", "-include/support/conf.h", "-include/support/log-level.h"]
        if gp11:
            args.append("-D__OPTEE_CORE_API_COMPAT_1_1=1")
        args += [f"-I{root}/{name}" for name in ("ta", "ta/include", "ta/src", "include") if (source / name).is_dir()]
        args += ["-I/support/devkit/include", "-I/support/clang/include", "-c", f"{root}/{rel}"]
        commands.append({"directory": f"{root}/ta", "file": f"{root}/{rel}", "arguments": args})
    (dest / "ta/compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    digest = hashlib.sha256("".join(f"{v}  {k}\n" for k, v in sorted(files.items())).encode()).hexdigest()
    print(json.dumps({ta: dict(source=source.resolve().relative_to(bench).as_posix(), files=files,
                               source_sha256=digest, gp_1_1=gp11)}, indent=2))


if __name__ == "__main__":
    main()
