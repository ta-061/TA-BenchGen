"""Recreate only the OP-TEE include trees used by the two measurements."""

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from urllib.request import Request, urlopen

RESULTS = Path(__file__).resolve().parents[1]
TA_INCLUDE_DIRS = [
    "lib/libutee/include",
    "lib/libutils/ext/include",
    "lib/libutils/isoc/include",
    "lib/libmbedtls/include",
    "lib/libmbedtls/mbedtls/include",
    "lib/libdl/include",
]


def header_record(folder):
    files = sorted(p for p in folder.rglob("*.h") if p.is_file())
    digest = sha256()
    for p in files:
        digest.update(f"{sha256(p.read_bytes()).hexdigest()}  {p.relative_to(folder).as_posix()}\n".encode())
    return {"headers": len(files), "sha256": digest.hexdigest()}


def install(output, expected, repository, revision, include_dirs):
    if output.exists():
        if header_record(output) != expected:
            raise ValueError(f"Header set differs from the measurement: {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary) / "include"
        staging.mkdir()
        url = f"https://codeload.github.com/OP-TEE/{repository}/tar.gz/{revision}"
        request = Request(url, headers={"User-Agent": "TA-BenchGen-replay"})
        with urlopen(request, timeout=90) as source, tarfile.open(fileobj=source, mode="r|gz") as archive:
            for member in archive:
                path = PurePosixPath(*PurePosixPath(member.name).parts[1:])
                if not member.isfile() or path.suffix not in {".h", ".S"} or ".." in path.parts:
                    continue
                for directory in include_dirs:
                    if path.is_relative_to(directory):
                        target = staging / path.relative_to(directory)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as src, target.open("wb") as dest:
                            shutil.copyfileobj(src, dest)
                        break
        if header_record(staging) != expected:
            raise ValueError(f"Header checksum differs at {repository}@{revision}")
        staging.rename(output)


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    records = json.loads((RESULTS / "2026-11-21/environment.json").read_text())["headers"]
    install(
        root / "devkit/include",
        records["ta"],
        "optee_os",
        "496fea3c81a4375e36b41423346499a85c89122e",
        TA_INCLUDE_DIRS,
    )
    install(
        root / "client",
        records["client"],
        "optee_client",
        "8533e0e6329840ee96cf81b6453f257204227e6c",
        ["public"],
    )
    print("Verified 196 TA headers and 5 client headers:", root)
