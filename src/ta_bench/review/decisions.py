"""Apply one human decision to the inspected records before publishing them."""
from ..common.jsonio import canonical_hash
from ..common.locking import now
from ..dataset.reviews import CHECKS, case_status, defect_versions, latest_reviews
from ..dataset.store import labels_digest


def record_decision(info, selected, reviewer, action, checks, reason, targets, required_reviewers):
    labels, hashes = info["labels"], info["hashes"]
    review = labels["review"]
    versions = info["defect_versions"]
    states = {did: ("unreviewed" if state == "stale" else state) for did, state in info["defect_statuses"].items()}
    entry = {"reviewer": reviewer, "at": now(), "action": action, "checks": checks, "reason": reason}
    if "per_defect" not in review and review["reviews"]:
        # Bind the old whole-case votes to their individual locations without rewriting any past vote.
        review["legacy_snapshot"] = {"against": hashes, "versions": versions}
    if len(selected) == 1:
        entry["defect_id"] = selected[0]["id"]
    change = None
    if targets is not None:
        defect, = selected
        change = {"defect_id": defect["id"], "reviewer": reviewer, "at": entry["at"], "reason": reason,
                  "before": defect["detector_targets"], "after": targets}
        entry["label_change"] = canonical_hash(change)
        defect["detector_targets"] = targets
        hashes = {**hashes, "labels": labels_digest(labels)}
    review["reviews"].append(entry)
    if change:
        versions = defect_versions(labels, hashes)
    entry.update(against=hashes, versions={d["id"]: versions[d["id"]] for d in selected})
    for defect in selected:
        did = defect["id"]
        if action in {"approve", "save"}:
            votes = latest_reviews(labels, did, hashes, versions[did]).values()
            count = sum(vote.get("action") == "approve" and all(vote["checks"][did].get(k) is True for k in CHECKS)
                        for vote in votes)
            states[did] = "approved" if count >= required_reviewers else "in_review"
        else:
            states[did] = "rejected" if action == "reject" else "in_review"
    review["per_defect"] = {did: {"status": state, "against": versions[did]} for did, state in states.items()}
    review["status"] = case_status(states)
    review["approved_against"] = hashes if review["status"] == "approved" else None
    return change
