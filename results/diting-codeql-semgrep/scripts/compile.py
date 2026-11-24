"""Compile the translation units listed for one CodeQL database."""
import json
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    for argv in json.loads(Path(sys.argv[1]).read_text()):
        subprocess.run(argv, check=True)
