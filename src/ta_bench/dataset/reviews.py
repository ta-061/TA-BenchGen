"""Review decisions, corrected locations and their on-disk history."""
from pathlib import Path

from ..common.jsonio import atomic_json, canonical_hash, load_json
from .schema import require, validate_labels

HISTORY_FILE = "label_history.json"
CHECKS = ("class", "location", "behavior")


def empty_review() -> dict:
    return {"status": "unreviewed", "reviews": [], "approved_against": None}


def public_labels(labels: dict) -> dict:
    status = "approved" if labels["review"]["status"] == "approved" else "unreviewed"
    return {**labels, "review": {"status": status}}


def _history_record(case_dir: Path, labels: dict) -> dict:
    path = case_dir / HISTORY_FILE
    if not path.exists():
        return {"case_id": labels["case_id"], "changes": []}
    require(path.is_file() and not path.is_symlink(), "invalid label correction history file")
    record = load_json(path)
    require(isinstance(record, dict) and record.get("case_id") == labels["case_id"], "invalid label history case")
    # If a writer stopped between renames, labels.json determines which history was committed.
    pending = record.pop("pending", None)
    if pending is not None:
        digest = canonical_hash(labels)
        require(digest in (pending["before"], pending["after"]), "labels changed during interrupted review save")
        if digest == pending["after"]:
            record = pending["history"]
            require(record["case_id"] == labels["case_id"], "invalid pending history case")
    return record


def read_review(case_dir: Path, labels: dict) -> tuple[dict, list]:
    """Return the working labels (including draft locations) and their verified edits."""
    validate_labels(labels)
    record = _history_record(case_dir, labels)
    review = record.get("review", labels["review"])
    if "review" in record:
        require(isinstance(review, dict) and isinstance(review.get("reviews"), list), "invalid review history")
        summary = public_labels({**labels, "review": review})["review"]
        require(labels["review"] == summary or
                (labels["review"] == empty_review() and summary["status"] == "unreviewed"),
                "review status differs from label history")
    elif set(review) == {"status"}:
        require(review["status"] == "unreviewed", "approved labels require review history")
        review = empty_review()
    references = [e["label_change"] for e in review["reviews"] if isinstance(e, dict) and "label_change" in e]
    changes = record.get("changes")
    # Older cases with decisions in labels.json could leave one uncommitted change after a crash.
    legacy_tail = int("reviews" in labels["review"] and "review" not in record)
    require(isinstance(changes, list) and len(references) <= len(changes) <= len(references) + legacy_tail,
            "invalid label history length")
    committed = changes[:len(references)]
    require([canonical_hash(change) for change in committed] == references, "label correction history mismatch")
    published = record.get("published_changes", len(committed))
    require(type(published) is int and 0 <= published <= len(committed)
            and (review["status"] != "approved" or published == len(committed)), "invalid published change count")
    stored_targets = {}
    last = {}
    for index, change in enumerate(committed):
        did = change["defect_id"]
        require(did not in last or last[did] == change["before"], "discontinuous label correction history")
        last[did] = change["after"]
        if index < published:
            stored_targets[did] = change["after"]
        else:
            stored_targets.setdefault(did, change["before"])
    targets = {d["id"]: d["detector_targets"] for d in labels["defects"]}
    require(all(targets.get(did) == value for did, value in stored_targets.items()),
            "corrected targets differ from label history")
    defects = [{**d, "detector_targets": last.get(d["id"], d["detector_targets"])} for d in labels["defects"]]
    working = {**labels, "defects": defects, "review": review}
    validate_labels(working)
    return working, committed


def publish_review(case_dir: Path, labels: dict, history: list, change: dict | None = None) -> None:
    """Under the review lock, save the decision and publish corrected locations on case approval."""
    label_file, history_file = case_dir / "labels.json", case_dir / HISTORY_FILE
    previous = load_json(label_file)
    previous_history = _history_record(case_dir, previous)
    changes = [*history, change] if change is not None else history
    record = {"case_id": labels["case_id"], "changes": changes, "review": labels["review"]}
    updated = public_labels(labels)
    if labels["review"]["status"] != "approved":
        published = previous_history.get("published_changes", len(history))
        if published < len(changes):
            record["published_changes"] = published
        # Keep generated or last approved locations on disk while the reviewer edits a draft.
        updated = {**previous, "review": updated["review"]}
        if previous["review"] == empty_review():
            updated = previous
    if updated != previous:
        pending = {"before": canonical_hash(previous), "after": canonical_hash(updated), "history": record}
        atomic_json(history_file, {**previous_history, "pending": pending})
        atomic_json(label_file, updated)
    atomic_json(history_file, record)


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
