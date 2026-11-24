"""Phase 4 of the public TEE Flow Inspector (candidate flows) with the GP 1.1 compatibility names.

For a TA compiled with -D__OPTEE_CORE_API_COMPAT_1_1=1, each identified sink that tee_api_compat.h
renames gets a copy under its __GP11_ name (ta_sinks_gp11.json), and the two entry points are given
together with their __GP11_ names. Other TAs get the public arguments unchanged.
Usage: phase4.py TA_ID RESULT_DIR   (RESULT_DIR holds ta_phase12.json and ta_sinks.json)
"""
import json
from pathlib import Path
import re
import subprocess
import sys

ta, dest = sys.argv[1], Path(sys.argv[2])
header = Path("/support/devkit/include/tee_api_compat.h")
aliases = dict(re.findall(r"^#define\s+(\w+)\s+(__GP11_\w+)\s*$", header.read_text(), re.M))
compiler = Path("/inputs") / ta / "ta/compile_commands.json"
gp11 = any("-D__OPTEE_CORE_API_COMPAT_1_1=1" in c["arguments"] for c in json.loads(compiler.read_text()))
sinks, sources = dest / "ta_sinks.json", ["TA_InvokeCommandEntryPoint", "TA_OpenSessionEntryPoint"]
if gp11:
    augmented = json.loads(sinks.read_bytes())
    rows = augmented["sinks"]
    augmented["sinks"] = rows + [dict(r, name=aliases[r["name"]]) for r in rows if r["name"] in aliases]
    sinks = dest / "ta_sinks_gp11.json"
    sinks.write_text(json.dumps(augmented, ensure_ascii=False, indent=2) + "\n")
    sources = sources + [aliases[k] for k in sources]
argv = [sys.executable, "/workspace/src/identify_flows/generate_candidate_flows.py",
        "--compile-db", str(compiler), "--sinks", str(sinks), "--phase12", str(dest / "ta_phase12.json"),
        "--sources", ",".join(sources), "--output", str(dest / "ta_candidate_flows.json"), "--devkit", "/support/devkit"]
(dest / "phase4-command.json").write_text(json.dumps(argv, indent=2) + "\n")
sys.exit(subprocess.run(argv, cwd=compiler.parent).returncode)
