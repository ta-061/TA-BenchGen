"""Phases 1-2 of the public TEE Flow Inspector (function classification, no LLM), as main.py runs them."""
import json
from pathlib import Path
import sys

sys.path.insert(0, "/workspace/src")
from classify.classifier import classify_functions  # noqa: E402

ta_dir, output = Path(sys.argv[1]), Path(sys.argv[2])
users, externals = classify_functions(ta_dir, ta_dir / "compile_commands.json")
output.write_text(json.dumps({"project_root": str(ta_dir), "user_defined_functions": users,
                              "external_declarations": externals}, indent=2, ensure_ascii=False))
print(f"{len(users)} user-defined functions, {len(externals)} external declarations")
