"""Schema of the persisted labels.json and verification.json records."""
from __future__ import annotations

import re

from ..candidate.check import validate_target_roles
from ..candidate.plan import validate_plan
from ..common.jsonio import canonical_hash
from ..errors import ExecutionError, ValidationError
from ..runtime.events import INSTRUMENTATION, collect_checkpoints, required_features, validate_receipts
from ..runtime.observations import comparison

SCHEMA_VERSION = "4.0"
CASE_ID = re.compile(r"case_[0-9a-f]{16,64}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
DEFECT_REVIEW_STATUSES = {"unreviewed", "in_review", "approved", "rejected"}
REVIEW_STATUSES = DEFECT_REVIEW_STATUSES | {"partially_approved"}
MACHINE_STATUSES = {"machine_pass", "machine_fail", "unknown", "unsupported", "execution_error"}
PLAN_FIELDS = ("id", "purpose", "targets", "steps", "witness_step")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate_labels(labels: dict) -> None:
    require(isinstance(labels, dict), "labels must be an object")
    require(labels.get("schema_version") == SCHEMA_VERSION, "unsupported labels schema_version")
    require(isinstance(labels.get("case_id"), str) and bool(CASE_ID.fullmatch(labels["case_id"])), "invalid case_id")
    normal = labels.get("normal")
    require(isinstance(normal, dict) and isinstance(normal.get("path"), str) and bool(normal["path"]), "normal.path is required")
    require(isinstance(normal.get("source_digest"), str) and bool(DIGEST.fullmatch(normal["source_digest"])), "invalid normal source_digest")
    defects = labels.get("defects")
    require(isinstance(defects, list) and bool(defects), "defects must be a nonempty list")
    ids = []
    for defect in defects:
        require(isinstance(defect, dict), "defect must be an object")
        did = defect.get("id")
        require(isinstance(did, str) and bool(re.fullmatch(r"D[1-9][0-9]*", did)), "invalid defect id")
        ids.append(did)
        require(isinstance(defect.get("class"), str) and bool(defect["class"]), "defect class required")
        require(isinstance(defect.get("reason"), str) and bool(defect["reason"].strip()), "defect reason required")
        require(isinstance(defect.get("edits"), list) and bool(defect["edits"]), "defect edits required")
        require(all(isinstance(edit, dict) for edit in defect["edits"]), "stored edits must be objects")
        validate_target_roles(defect.get("detector_targets"))
        witness = defect.get("witness_test_ids")
        require(isinstance(witness, list) and bool(witness) and all(isinstance(x, str) and x for x in witness), "witness_test_ids required")
        require(len(witness) == len(set(witness)), "duplicate witness_test_ids")
    require(len(ids) == len(set(ids)), "duplicate defect ids")
    review = labels.get("review")
    require(isinstance(review, dict) and review.get("status") in REVIEW_STATUSES, "invalid review.status")
    if set(review) == {"status"}:
        require(review["status"] in {"unreviewed", "approved"}, "invalid published review status")
        return
    require(isinstance(review.get("reviews"), list), "review.reviews must be a list")
    if "legacy_snapshot" in review:
        snapshot = review["legacy_snapshot"]
        require(isinstance(snapshot, dict) and isinstance(snapshot.get("against"), dict)
                and isinstance(snapshot.get("versions"), dict) and set(snapshot["versions"]) == set(ids),
                "invalid legacy review snapshot")
    if "per_defect" in review:
        states = review["per_defect"]
        require(isinstance(states, dict) and set(states) == set(ids), "invalid per-defect review IDs")
        for state in states.values():
            require(isinstance(state, dict) and state.get("status") in DEFECT_REVIEW_STATUSES
                    and isinstance(state.get("against"), str) and bool(DIGEST.fullmatch(state["against"])),
                    "invalid per-defect review")
    require(review["status"] != "partially_approved" or "per_defect" in review, "missing per-defect reviews")
    require("approved_against" in review and (review["approved_against"] is None or isinstance(review["approved_against"], dict)), "invalid approved_against")
    if review["status"] == "approved":
        require(isinstance(review["approved_against"], dict) and bool(review["approved_against"]), "approved record requires hashes")


def validate_verification(verification: dict, labels: dict) -> None:
    require(isinstance(verification, dict), "verification must be an object")
    require(verification.get("schema_version") == SCHEMA_VERSION, "unsupported verification schema_version")
    require(verification.get("case_id") == labels["case_id"], "verification case_id mismatch")
    environment = verification.get("environment")
    require(isinstance(environment, dict), "environment required")
    for key in ("optee_revision", "qemu_revision", "toolchain", "image_digest", "runner_version"):
        require(isinstance(environment.get(key), str) and bool(environment[key]), f"environment.{key} required")
    require(bool(DIGEST.fullmatch(environment["image_digest"])), "invalid image_digest")
    generation = verification.get("generation")
    require(isinstance(generation, dict), "generation required")
    require(isinstance(generation.get("model_id"), str) and bool(generation["model_id"]), "generation.model_id required")
    for key in ("attempt_index", "attempts_total"):
        require(type(generation.get(key)) is int and generation[key] >= 1, f"invalid generation.{key}")
    require(generation["attempt_index"] <= generation["attempts_total"], "attempt_index exceeds attempts_total")
    require(isinstance(generation.get("plan_digest"), str) and bool(DIGEST.fullmatch(generation["plan_digest"])), "invalid plan_digest")
    semantic = verification.get("semantic")
    require(isinstance(semantic, dict), "semantic required")
    machine = semantic.get("machine_validation")
    require(isinstance(machine, dict) and machine.get("status") in MACHINE_STATUSES, "invalid machine_validation")
    require(isinstance(machine.get("per_defect"), dict), "per_defect required")
    require(set(machine["per_defect"]) == {d["id"] for d in labels["defects"]}, "per_defect IDs mismatch")
    require(all(v in MACHINE_STATUSES for v in machine["per_defect"].values()), "invalid per_defect status")
    require(type(machine.get("repetitions")) is int and machine["repetitions"] >= 2, "at least two repetitions required")
    tests = semantic.get("tests")
    require(isinstance(tests, list) and bool(tests), "semantic.tests required")
    plan = validate_plan([{k: v for k, v in test.items() if k in PLAN_FIELDS}
                          for test in tests if isinstance(test, dict)], labels["defects"])
    require(canonical_hash(plan) == generation["plan_digest"], "plan_digest does not match stored input plan")
    features = set().union(*(required_features(test['steps']) for test in plan))
    if features:
        require(semantic.get('execution') == {'features': sorted(features),
                'instrumentation': INSTRUMENTATION, 'checkpoints': collect_checkpoints(plan)},
                'execution capabilities/checkpoints do not match frozen input plan')

    def check_receipts(test, rows):
        try:
            for step, row in zip(test['steps'], rows):
                require(isinstance(row, dict), 'invalid event observation')
                validate_receipts(step, row)
        except ExecutionError as exc:
            raise ValidationError(str(exc)) from exc

    test_map = {}
    for test in tests:
        require(isinstance(test, dict) and isinstance(test.get("id"), str) and bool(test["id"]), "test id required")
        require(test["id"] not in test_map, "duplicate test id")
        test_map[test["id"]] = test
        require(test.get("purpose") in {"normal", "witness"}, "invalid test purpose")
        require(isinstance(test.get("steps"), list) and bool(test["steps"]), "test steps required")
        require(isinstance(test.get("targets"), list) and all(t in machine["per_defect"] for t in test["targets"]), "invalid test targets")
        observed = test.get("observed")
        require(isinstance(observed, dict), "test observations required")
        for variant in ("normal", "defective"):
            require(isinstance(observed.get(variant), list) and len(observed[variant]) == len(test["steps"]), "observation count must match steps")
            check_receipts(test, observed[variant])
        require(type(test.get("equal")) is bool or test.get("equal") is None, "invalid test equal")
        for variant in ("normal", "defective"):
            for row, step in zip(observed[variant], test["steps"]):
                require(isinstance(row, dict) and row.get("op") == step["op"], "observation operation mismatch")
                require(type(row.get("result")) is int and 0 <= row["result"] <= 0xffffffff, "invalid observed result")
                require(type(row.get("origin")) is int and 0 <= row["origin"] <= 0xffffffff, "invalid observed origin")
                require(type(row.get("ta_crashed")) is bool and isinstance(row.get("params"), list), "invalid observation fields")
        repeated = test.get("repeated_observed")
        if repeated is not None:
            require(isinstance(repeated, dict) and all(isinstance(repeated.get(v), list)
                     and len(repeated[v]) == len(test["steps"]) for v in ("normal", "defective")), "invalid repeated observations")
            for variant in ('normal', 'defective'):
                check_receipts(test, repeated[variant])
        # Items that two runs of the same version did not reproduce are not compared. Records written before
        # variable_items existed carry excluded_steps; both are recomputed from the observations.
        variable, view = comparison(*([(observed[v], repeated[v]) for v in ("normal", "defective")] if repeated else []))
        if not repeated:
            variable = [[] for _ in test["steps"]]
        recorded = [{"step": i + 1, "items": items} for i, items in enumerate(variable) if items]
        if "variable_items" in test:
            require(test["variable_items"] == recorded, "variable_items do not match repeated observations")
        elif "repeated_observed" in test:
            require(not (recorded and machine["status"] == "machine_pass"),
                    "case predates variable_items; run review --reverify")
        different = [i + 1 for i, (a, b) in enumerate(zip(view(observed["normal"]), view(observed["defective"]))) if a != b]
        require(test["equal"] is (not different), "equal does not match observations")
        if "different_steps" in test:
            require(test["different_steps"] == different, "different_steps does not match observations")
        if machine["status"] == "machine_pass" and test["purpose"] == "witness":
            require(not any(row["ta_crashed"] for row in observed["normal"]), "normal TA crashed in witness")
            require(any(n >= test["witness_step"] for n in different), "witness difference is missing")
        if test["purpose"] == "normal":
            require(not test["targets"], "normal test must have no targets")
        else:
            require(bool(test["targets"]), "witness must target a defect")
            require(type(test.get("witness_step")) is int and 1 <= test["witness_step"] <= len(test["steps"]), "invalid witness_step")
    require(any(t["purpose"] == "normal" for t in tests), "at least one normal test required")
    for defect in labels["defects"]:
        for tid in defect["witness_test_ids"]:
            require(tid in test_map and test_map[tid]["purpose"] == "witness" and defect["id"] in test_map[tid]["targets"], "witness reference mismatch")
    # Records saved while every edit was also reverted alone carry semantic.necessity; it is not read.
    if features and machine['status'] == 'machine_pass':
        for experiment in semantic.get('defect_reverts', []):
            require(isinstance(experiment, dict) and isinstance(experiment.get('tests'), list)
                    and bool(experiment['tests']), 'event revert evidence required')
            for evidence in experiment['tests']:
                require(isinstance(evidence, dict) and evidence.get('test_id') in test_map,
                        'invalid event revert test')
                test = test_map[evidence['test_id']]
                repetitions = evidence.get('observed')
                require(isinstance(repetitions, list) and len(repetitions) == machine['repetitions'],
                        'event revert repetitions required')
                for rows in repetitions:
                    require(isinstance(rows, list) and len(rows) == len(test['steps']),
                            'incomplete event revert observations')
                    check_receipts(test, rows)
    if machine["status"] == "machine_pass":
        require(all(v == "machine_pass" for v in machine["per_defect"].values()), "machine pass requires all defects to pass")
        if len(labels["defects"]) > 1:
            groups = semantic.get("defect_reverts")
            require(isinstance(groups, list) and len(groups) == len(labels["defects"]), "defect reverts required for multiple defects")
            require(all(isinstance(g, dict) for g in groups) and {g.get("defect_id") for g in groups} == set(machine["per_defect"]), "defect revert IDs mismatch")
            require(all(g.get("witness_matches_normal_after_revert") is True for g in groups), "all defect revert checks must pass")
        require(all(t["equal"] is True for t in tests if t["purpose"] == "normal"), "normal tests must agree")
        require(all(t["equal"] is False for t in tests if t["purpose"] == "witness"), "witness tests must differ")
    require(isinstance(verification.get("run_meta"), dict), "run_meta required")
