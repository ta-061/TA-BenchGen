"""Review decisions for individual defects and the separate label correction history."""
from pathlib import Path

from ..common.jsonio import canonical_hash, load_json
from .schema import require

HISTORY_FILE = "label_history.json"
CHECKS = ("class", "location", "behavior")


def read_label_history(case_dir: Path, labels: dict) -> list:
    # Publish the sidecar first. The references in the atomically replaced labels.json commit
    # its entries. After an interrupted save, readers ignore the tail and the next edit replaces it.
    references = [e["label_change"] for e in labels["review"]["reviews"] if isinstance(e, dict) and "label_change" in e]
    path = case_dir / HISTORY_FILE
    if not path.exists():
        require(not references, "missing label correction history")
        return []
    require(path.is_file() and not path.is_symlink(), "invalid label correction history file")
    record = load_json(path)
    require(isinstance(record, dict) and record.get("case_id") == labels["case_id"], "invalid label history case")
    changes = record.get("changes")
    require(isinstance(changes, list) and len(references) <= len(changes) <= len(references) + 1,
            "invalid label history length")
    committed = changes[:len(references)]
    require([canonical_hash(change) for change in committed] == references, "label correction history mismatch")
    last = {}
    for change in committed:
        did = change["defect_id"]
        require(did not in last or last[did] == change["before"], "discontinuous label correction history")
        last[did] = change["after"]
    targets = {d["id"]: d["detector_targets"] for d in labels["defects"]}
    require(all(targets.get(did) == value for did, value in last.items()), "corrected targets differ from label history")
    return committed


def defect_versions(labels: dict, hashes: dict) -> dict:
    shared = {k: v for k, v in hashes.items() if k != "labels"}
    context = {k: v for k, v in labels.items() if k not in {"defects", "review"}}
    revisions = {entry["defect_id"]: entry["label_change"] for entry in labels["review"]["reviews"]
                 if isinstance(entry, dict) and "label_change" in entry}
    return {d["id"]: canonical_hash([shared, context, d, revisions.get(d["id"])]) for d in labels["defects"]}


def defect_statuses(labels: dict, hashes: dict, versions: dict) -> dict:
    review = labels["review"]
    if "per_defect" not in review:
        # Versions predating individual decisions approved or rejected the entire case.
        status = review["status"]
        if status == "approved" and review["approved_against"] != hashes:
            status = "stale"
        return dict.fromkeys(versions, status)
    states = {}
    for did, version in versions.items():
        saved = review["per_defect"][did]
        states[did] = saved["status"] if saved["against"] == version else (
            "stale" if saved["status"] == "approved" else "unreviewed")
    return states


def latest_reviews(labels: dict, did: str, hashes: dict, version: str) -> dict:
    """Last vote per person on this defect. A scoped vote never supersedes a sibling's vote."""
    review = labels["review"]
    legacy = review.get("legacy_snapshot", {"against": hashes, "versions": {did: version}})
    latest = {}
    for entry in review["reviews"]:
        if (isinstance(entry, dict) and isinstance(entry.get("reviewer"), str)
                and isinstance(entry.get("checks"), dict) and isinstance(entry["checks"].get(did), dict)):
            binding = entry.get("versions", {})
            if "versions" not in entry and entry.get("against") == legacy["against"]:
                binding = legacy["versions"]
            name = entry["reviewer"]
            if isinstance(binding, dict) and binding.get(did) == version:
                latest[name] = entry
            else:
                latest.pop(name, None)
    return latest


def case_status(states: dict) -> str:
    values = set(states.values())
    if len(values) == 1:
        return next(iter(values))
    return "partially_approved" if "approved" in values else "in_review"
