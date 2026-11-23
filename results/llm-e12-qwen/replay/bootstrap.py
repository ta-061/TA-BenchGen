"""Invoke the original process_project with a prepared compilation database.

The source, prompt, parsing, sink, flow, analysis and report functions retain
their original behavior. Only empty-workspace cleanup and the build frontend
are bypassed: bear is unavailable, and the original build fallback generates
a parser compilation database rather than a linked executable as well.
"""
import importlib.util
from pathlib import Path
import sys


def main():
    runtime, project, output, sdk = map(Path, sys.argv[1:5])
    sys.path.insert(0, str(runtime / "src"))
    spec = importlib.util.spec_from_file_location("legacy_original_main", runtime / "src/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DEVKIT = sdk
    module.clean_project_dependencies = lambda *args, **kwargs: None
    module.ensure_ta_db = lambda ta_dir, *args, **kwargs: ta_dir / "compile_commands.json"
    identify = runtime / "src/identify_sinks/identify_sinks.py"
    module.process_project(project, identify, False,
                           "experiments/e12_general_sink_screening", output)


if __name__ == "__main__":
    main()
