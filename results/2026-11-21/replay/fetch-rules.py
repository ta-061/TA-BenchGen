"""Fetch the two Semgrep registry revisions used in this measurement."""
from hashlib import sha256
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from measure import RULES_SHA


def fetch():
    rules = [("jQTzvry", "c.lang.security.random-fd-exhaustion.random-fd-exhaustion"),
             ("YDTvRlQ", "c.lang.security.insecure-use-gets-fn.insecure-use-gets-fn")]
    profile = ["rules:"]
    for version, name in rules:
        request = Request(f"https://semgrep.dev/c/r/{version}/{name}",
                          headers={"User-Agent": "Semgrep/1.164.0"})
        with urlopen(request, timeout=30) as response:
            lines = response.read().decode().splitlines()
        if lines[0] != "rules:" or not lines[1].startswith("- id: "):
            raise ValueError(f"Unexpected registry response for {name}")
        # The profile used qualified IDs and predates the registry's display-path field.
        profile.append("- id: " + name)
        profile.extend(line for line in lines[2:] if not line.startswith("        path: "))
    content = ("\n".join(profile) + "\n").encode()
    if sha256(content).hexdigest() != RULES_SHA:
        raise ValueError("The downloaded revisions do not reproduce the measured profile.")
    return content


if __name__ == "__main__":
    Path(sys.argv[1]).write_bytes(fetch())
