"""Run the pinned Phase 5 entry point with auditable OpenAI Responses transport."""
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import re
import runpy
import sqlite3
import sys
import time
import uuid

import openai
from openai._models import construct_type
from openai.resources.responses.responses import Responses
from openai.types.responses import Response


MODEL = "gpt-5.2-2025-12-11"
WORK = Path("/work")


def append(path, data):
    with path.open("a") as out:
        print(json.dumps(dict(unix=time.time(), **data), separators=(",", ":")), file=out, flush=True)


def safe_field(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.\[\]-]{1,70}", value) else None


def blocked(reason, status=None, code=None, param=None):
    data = dict(reason=reason, http_status=status, api_code=safe_field(code), param=safe_field(param))
    tmp = WORK / ("block-" + uuid.uuid4().hex)
    tmp.write_text(json.dumps(data) + "\n")
    try:
        os.link(tmp, WORK / "block.json")
    except FileExistsError:
        pass
    finally:
        tmp.unlink()
    raise SystemExit(77)


def wait_for_slot():
    while True:
        if (WORK / "block.json").exists():
            raise SystemExit(77)
        path = WORK / "cooldown-until"
        delay = float(path.read_text()) - time.time() if path.exists() else 0
        if delay <= 0:
            return
        time.sleep(min(5.0, delay))


def backoff(error, attempt):
    headers = getattr(getattr(error, "response", None), "headers", {})
    delay = min(90, 2 ** min(attempt + 1, 7))
    for field, scale in [("retry-after-ms", .001), ("retry-after", 1)]:
        try:
            delay = max(delay, float(headers.get(field, "")) * scale)
        except ValueError:
            pass
    end = time.time() + delay + random.uniform(.5, 3)
    path = WORK / "cooldown-until"
    with (WORK / "cooldown.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists() or float(path.read_text()) < end:
            tmp = WORK / "cooldown.tmp"
            tmp.write_text(str(end))
            tmp.replace(path)
    time.sleep(random.uniform(.2, 2))


def measure(ta, attempt_dir, cache_dir):
    # Keys enter the SDK only inside this child process. Docker argv and results carry no credentials.
    os.environ["OPENAI_API_KEY"] = Path("/secrets/openai.key").read_text().strip()
    os.environ.pop("OPENAI_LOG", None)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(cache_dir / "responses.db")
    cache.execute("CREATE TABLE IF NOT EXISTS response (key TEXT, occurrence INTEGER, body TEXT NOT NULL,"
                  " PRIMARY KEY(key,occurrence))")
    occurrence = Counter()
    original = Responses.create
    log = attempt_dir / "api-usage.jsonl"

    def recorded(resource, *args, **kw):
        if (args or kw.get("model") != MODEL or str(resource._client.base_url).rstrip("/") != "https://api.openai.com/v1"
                or kw.get("tools") or kw.get("store") is not False or kw.get("reasoning", {}).get("effort") != "none"):
            blocked("unexpected_request_configuration")
        key = hashlib.sha256(json.dumps(kw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        occurrence[key] += 1
        n = occurrence[key]
        common = dict(ta=ta, request_key=key, occurrence=n)
        cached = cache.execute("SELECT body FROM response WHERE key=? AND occurrence=?", (key, n)).fetchone()
        if cached:
            # Use the pinned SDK's normal response decoder for newer API enum values.
            reply = construct_type(type_=Response, value=json.loads(cached[0]))
            append(log, dict(common, event="delivered", source="replay", response_id=reply.id))
            return reply
        success = WORK / "first-response.ok"
        with (WORK / "first-request.lock").open("a") as gate:
            if not success.exists():
                fcntl.flock(gate, fcntl.LOCK_EX)
                if success.exists():
                    fcntl.flock(gate, fcntl.LOCK_UN)
            resource._client.max_retries = 0
            limit = kw.get("max_output_tokens", 16384)
            network_errors = 0
            while True:
                wait_for_slot()
                started = time.monotonic()
                try:
                    reply = original(resource, **dict(kw, max_output_tokens=limit))
                except (openai.APIConnectionError, openai.APIStatusError) as exc:
                    status = getattr(exc, "status_code", None)
                    code = getattr(exc, "code", None)
                    append(log, dict(common, event="api_error", http_status=status, code=safe_field(code)))
                    if status in (401, 403, 404) or code in ("insufficient_quota", "billing_hard_limit_reached", "billing_not_active"):
                        blocked("credential_access_or_quota", status, code, getattr(exc, "param", None))
                    if status == 429:
                        network_errors += 1
                        backoff(exc, network_errors)
                        continue
                    if status is None or status in (408, 409) or status >= 500:
                        network_errors += 1
                        if network_errors < 8:
                            backoff(exc, network_errors)
                            continue
                        raise SystemExit(75)
                    blocked("api_request_rejected", status, code, getattr(exc, "param", None))
                usage = reply.usage.model_dump() if reply.usage else {}
                event = dict(common, source="live", response_id=reply.id, model=reply.model, status=reply.status,
                             duration_seconds=round(time.monotonic()-started, 3), usage=usage, max_output_tokens=limit)
                if reply.model != MODEL:
                    append(log, dict(event, event="unaccepted"))
                    blocked("model_snapshot_mismatch")
                if reply.status != "completed" or not (reply.output_text or "").strip():
                    reason = getattr(reply.incomplete_details, "reason", None)
                    append(log, dict(event, event="unaccepted", reason=safe_field(reason)))
                    if reason == "max_output_tokens" and limit == 16384:
                        limit = 32768
                        continue
                    raise SystemExit(65)
                with cache:
                    cache.execute("INSERT INTO response VALUES (?,?,?)", (key, n, reply.model_dump_json()))
                append(log, dict(event, event="delivered"))
                success.touch(exist_ok=True)
                return reply
    Responses.create = recorded


def main():
    ta, folder, cache = sys.argv[1:4]
    measure(ta, Path(folder), Path(cache))
    # TA_PHASE_PROGRAM selects another unmodified phase program, e.g. identify_sinks/identify_sinks.py.
    analyzer = Path("/workspace/src") / os.environ.get("TA_PHASE_PROGRAM", "analyze_vulnerabilities/taint_analyzer.py")
    sys.argv = [str(analyzer), *sys.argv[4:]]
    sys.path.insert(0, str(analyzer.parent))
    runpy.run_path(str(analyzer), run_name="__main__")


if __name__ == "__main__":
    main()
