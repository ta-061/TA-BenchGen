#!/usr/bin/env python3
"""Record the exit status of each CodeQL call made by the DITING postprocessor."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

argv = [os.environ["DITING_CLI"], *sys.argv[1:],
        "--common-caches=" + os.environ["DITING_CACHE"], "--threads=2", "--ram=2048"]
start = time.monotonic()
stamp = datetime.now(timezone.utc).isoformat()
rc = subprocess.run(argv).returncode
with Path(os.environ["DITING_TRACE"]).open("a") as trace:
    record = {"argv": argv, "cwd": str(Path.cwd()), "started_utc": stamp,
              "seconds": round(time.monotonic() - start, 3), "exit_code": rc}
    trace.write(json.dumps(record) + "\n")
sys.exit(rc)
