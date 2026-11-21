import shutil
from copy import deepcopy

import pytest

from ta_bench.candidate.c_source import function_ranges
from ta_bench.candidate.check import check_candidate
from ta_bench.candidate.diff import compute_diff, compute_edits, revert_edits
from ta_bench.common.jsonio import atomic_json, canonical_hash, load_json
from ta_bench.common.sources import source_digest
from ta_bench.dataset.duplicates import check_duplicates
from ta_bench.dataset.store import approval_hashes, inspect_case, save_case
from ta_bench.errors import ValidationError

CLASSES = {"IVW": {"supported": True, "description": "Input validation weakness"}}
NORMAL = """int read_slot(int index) {
    if (index >= 8)
        return -1;
    return index + 1;
}
"""
DEFECTIVE = """int read_slot(int index) {
    return index + 1;
}
"""


@pytest.fixture
def trees(tmp_path):
    normal = tmp_path / "benchmark" / "normal" / "sample"
    (normal / "ta").mkdir(parents=True)
    (normal / "ta" / "entry.c").write_text(NORMAL)
    (normal / "Makefile").write_text("all:\n\ttrue\n")
    defective = tmp_path / "candidate"
    shutil.copytree(normal, defective)
    (defective / "ta" / "entry.c").write_text(DEFECTIVE)
    return normal, defective


def defect():
    return {"id": "D1", "class": "IVW", "edits": ["E1"],
            "detector_targets": [{"path": "ta/entry.c", "function": "read_slot", "lines": [2, 2], "role": "effect"}],
            "witness_test_ids": ["T02"], "reason": "Bounds check is removed"}


def records(normal, defective):
    labels = {"schema_version": "4.0", "case_id": "case_0123456789abcdef",
              "normal": {"path": "normal/sample", "source_digest": source_digest(normal)},
              "defects": check_candidate(normal, defective, [defect()], CLASSES),
              "review": {"status": "unreviewed", "reviews": [], "approved_against": None}}
    steps = [{"op": "open", "session": "s1"},
             {"op": "invoke", "session": "s1", "command_id": 0, "params": [{"type": "none"}] * 4}]
    observations = [{"op": step["op"], "result": 0, "origin": 4, "params": [], "ta_crashed": False} for step in steps]
    normal_witness = deepcopy(observations)
    normal_witness[1]["result"] = 1
    tests = [{"id": "T01", "purpose": "normal", "targets": [], "steps": deepcopy(steps),
              "observed": {"normal": deepcopy(observations), "defective": deepcopy(observations)}, "equal": True},
             {"id": "T02", "purpose": "witness", "targets": ["D1"], "witness_step": 2,
              "steps": deepcopy(steps), "observed": {"normal": normal_witness, "defective": deepcopy(observations)}, "equal": False}]
    verification = {"schema_version": "4.0", "case_id": labels["case_id"],
                    "environment": {"optee_revision": "test", "qemu_revision": "test", "toolchain": "test", "image_digest": "sha256:" + "0" * 64, "runner_version": "test"},
                    "generation": {"model_id": "fixture", "attempt_index": 1, "attempts_total": 1, "plan_digest": canonical_hash([{k: v for k, v in t.items() if k not in {"observed", "equal"}} for t in tests])},
                    "semantic": {"tests": tests,
                                 "machine_validation": {"status": "machine_pass", "per_defect": {"D1": "machine_pass"}, "repetitions": 2}},
                    "run_meta": {"verified_at": "2026-11-14T00:00:00Z", "run_id": "test"}}
    return labels, verification


def publish(trees):
    normal, defective = trees
    labels, verification = records(normal, defective)
    benchmark = normal.parent.parent
    case = save_case(benchmark / "defective", defective, labels, verification, compute_diff(normal, defective))
    return benchmark, case


def test_deleted_guard_has_mechanical_edit_and_live_target(trees):
    normal, defective = trees
    result = check_candidate(normal, defective, [defect()], CLASSES)
    assert result[0]["edits"] == [{"edit_id": "E1", "path": "ta/entry.c", "kind": "delete", "normal_lines": [2, 3], "defective_lines": None}]
    assert "-    if (index >= 8)" in compute_diff(normal, defective)


@pytest.mark.parametrize("path", ["Makefile", "host/driver.c", "ta/build.mk", "ta/tool.py", "ta/entry.c/extra"])
def test_non_ta_source_change_rejected(trees, path):
    normal, defective = trees
    if path == "ta/entry.c/extra":
        (defective / "ta" / "entry.c").unlink()
    target = defective / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("modified")
    with pytest.raises(ValidationError):
        check_candidate(normal, defective, [defect()], CLASSES)


def test_file_rename_and_symlink_rejected(trees):
    normal, defective = trees
    (defective / "ta" / "entry.c").rename(defective / "ta" / "other.c")
    with pytest.raises(ValidationError, match="additions"):
        compute_edits(normal, defective)
    (defective / "ta" / "entry.c").symlink_to(normal / "ta" / "entry.c")
    with pytest.raises(ValidationError, match="symlinks"):
        source_digest(defective)


def test_unchanged_host_is_hashed(trees):
    normal, _ = trees
    before = source_digest(normal)
    (normal / "Makefile").write_text("all: changed\n")
    assert source_digest(normal) != before


def test_permissions_cannot_change(trees):
    normal, defective = trees
    (defective / "Makefile").chmod(0o755)
    with pytest.raises(ValidationError, match="permissions"):
        compute_edits(normal, defective)


@pytest.mark.parametrize("bad", [
    {"edits": []}, {"edits": ["E1", "E1"]}, {"edits": ["E2"]},
    {"detector_targets": [{"path": "ta/entry.c", "function": "read_slot", "lines": [4, 4], "role": "effect"}]},
    {"detector_targets": [{"path": "ta/entry.c", "function": "absent", "lines": [2, 2], "role": "effect"}]},
    {"detector_targets": [{"path": "ta/../ta/entry.c", "function": "read_slot", "lines": [2, 2], "role": "effect"}]},
])
def test_bad_edit_attribution_and_targets(trees, bad):
    normal, defective = trees
    record = defect()
    record.update(bad)
    with pytest.raises(ValidationError):
        check_candidate(normal, defective, [record], CLASSES)


def test_double_attribution_rejected(trees):
    normal, defective = trees
    second = defect()
    second["id"] = "D2"
    with pytest.raises(ValidationError, match="exactly one"):
        check_candidate(normal, defective, [defect(), second], CLASSES)


def test_forged_edit_metadata_rejected(trees):
    normal, defective = trees
    record = defect()
    record["edits"] = [dict(compute_edits(normal, defective)[0], normal_lines=[1, 5])]
    with pytest.raises(ValidationError, match="metadata"):
        check_candidate(normal, defective, [record], CLASSES)


@pytest.mark.parametrize("text", ["/* IVW */", "/* intentionally vulnerable */", "int injected_flag;", "char *s = \"defect\";", "int unsafeIndex;", "/* 脆弱性 */"])
def test_changed_source_clues_rejected(trees, text):
    normal, defective = trees
    (defective / "ta" / "entry.c").write_text(DEFECTIVE.replace("    return", f"    {text}\n    return"))
    record = defect()
    record["detector_targets"][0]["lines"] = [3, 3]
    with pytest.raises(ValidationError, match="clue"):
        check_candidate(normal, defective, [record], CLASSES)


def test_existing_comment_not_flagged(trees):
    normal, defective = trees
    for tree in (normal, defective):
        path = tree / "ta" / "entry.c"
        path.write_text(path.read_text() + "/* unsafe old comment */\n")
    assert check_candidate(normal, defective, [defect()], CLASSES)


def test_revert_each_edit_preserves_other_changes(tmp_path, trees):
    normal, defective = trees
    (normal / "ta" / "entry.c").write_text(NORMAL + "\nint value(void) {\n    return 3;\n}\n")
    (defective / "ta" / "entry.c").write_text(DEFECTIVE + "\nint value(void) {\n    return 4;\n}\n")
    assert len(compute_edits(normal, defective)) == 2
    out = tmp_path / "revert-one"
    revert_edits(normal, defective, out, ["E1"])
    assert (out / "ta" / "entry.c").read_text() == NORMAL + "\nint value(void) {\n    return 4;\n}\n"
    out2 = tmp_path / "revert-both"
    revert_edits(normal, defective, out2, ["E1", "E2"])
    assert source_digest(out2) == source_digest(normal)


def test_insert_revert_and_missing_newline(tmp_path, trees):
    normal, defective = trees
    (normal / "ta" / "entry.c").write_text("int f(void) {\n    return 1;\n}")
    (defective / "ta" / "entry.c").write_text("int f(void) {\n    int a = 0;\n    return 1;\n}")
    assert compute_edits(normal, defective)[0]["normal_lines"] is None
    assert "No newline" in compute_diff(normal, defective)
    revert_edits(normal, defective, tmp_path / "revert", ["E1"])
    assert source_digest(tmp_path / "revert") == source_digest(normal)


def test_masked_literals_and_function_ranges():
    source = '/* void fake() { } */\nint f(void) {\n char *s = "}";\n return 1;\n}\n'
    assert function_ranges(source) == {"f": [(2, 5)]}


def test_atomic_four_element_case_and_inspect(trees):
    benchmark, case = publish(trees)
    assert {p.name for p in case.iterdir()} == {"source", "labels.json", "changes.diff", "verification.json"}
    info = inspect_case(case, benchmark, CLASSES)
    assert info["warnings"] == []
    assert info["status"] == "unreviewed"
    assert len(info["hashes"]) == 5


def test_approval_ignores_run_meta_but_tracks_semantic(trees):
    normal, _ = trees
    benchmark, case = publish(trees)
    labels = load_json(case / "labels.json")
    labels["review"].update(status="approved", reviews=[], approved_against=approval_hashes(case, normal))
    atomic_json(case / "labels.json", labels)
    assert inspect_case(case, benchmark, CLASSES)["status"] == "approved"
    verification = load_json(case / "verification.json")
    verification["run_meta"]["verified_at"] = "tomorrow"
    atomic_json(case / "verification.json", verification)
    assert inspect_case(case, benchmark, CLASSES)["status"] == "approved"
    verification["semantic"]["tests"][1]["observed"]["defective"][0]["result"] = 7
    atomic_json(case / "verification.json", verification)
    assert inspect_case(case, benchmark, CLASSES)["status"] == "stale"


def test_baseline_and_label_tampering_stale(trees):
    normal, _ = trees
    benchmark, case = publish(trees)
    labels = load_json(case / "labels.json")
    labels["review"].update(status="approved", reviews=[], approved_against=approval_hashes(case, normal))
    atomic_json(case / "labels.json", labels)
    labels["defects"][0]["reason"] += " changed"
    atomic_json(case / "labels.json", labels)
    assert inspect_case(case, benchmark, CLASSES)["status"] == "stale"
    (normal / "Makefile").write_text("changed\n")
    assert inspect_case(case, benchmark, CLASSES)["status"] == "stale"


def test_broken_diff_and_missing_element_unapprovable(trees):
    benchmark, case = publish(trees)
    (case / "changes.diff").write_text("forged")
    info = inspect_case(case, benchmark, CLASSES)
    assert info["status"] == "invalid" and info["warnings"]
    (case / "verification.json").unlink()
    assert inspect_case(case, benchmark, CLASSES)["status"] == "invalid"


def test_only_machine_pass_can_be_saved(trees):
    normal, defective = trees
    labels, verification = records(normal, defective)
    verification["semantic"]["machine_validation"]["status"] = "unknown"
    with pytest.raises(ValidationError, match="only machine_pass"):
        save_case(normal.parent.parent / "defective", defective, labels, verification, compute_diff(normal, defective))


def test_duplicates_rejected(trees):
    normal, defective = trees
    benchmark, _ = publish(trees)
    with pytest.raises(ValidationError, match="duplicate"):
        check_duplicates(normal, defective, check_candidate(normal, defective, [defect()], CLASSES),
                         benchmark / "defective")


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"status":"machine_fail","status":"machine_pass"}')
    with pytest.raises(ValidationError, match="duplicate JSON"):
        load_json(path)


def test_a_record_saved_with_per_edit_reverts_stays_valid(trees):
    from ta_bench.dataset.schema import validate_verification
    normal, defective = trees
    labels, verification = records(normal, defective)
    verification["semantic"]["necessity"] = [{"edit_id": "E1", "witness_matches_normal_after_revert": True}]
    validate_verification(verification, labels)


def test_forged_equal_does_not_pass_integrity(trees):
    benchmark, case = publish(trees)
    verification = load_json(case / "verification.json")
    verification["semantic"]["tests"][1]["observed"]["defective"] = deepcopy(verification["semantic"]["tests"][1]["observed"]["normal"])
    atomic_json(case / "verification.json", verification)
    info = inspect_case(case, benchmark, CLASSES)
    assert info["status"] == "invalid"
    assert not info["structural_valid"]


@pytest.mark.parametrize("bad", [[], {}])
def test_unhashable_edit_id_is_validation_error(trees, bad):
    normal, defective = trees
    record = defect()
    record["edits"] = [{"edit_id": bad}]
    with pytest.raises(ValidationError, match="unknown edit"):
        check_candidate(normal, defective, [record], CLASSES)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "\ud800"])
def test_atomic_json_rejects_noncanonical_values_before_writing(tmp_path, bad):
    target = tmp_path / "result.json"
    with pytest.raises(ValidationError):
        atomic_json(target, {"value": bad})
    assert not target.exists()


def test_changes_replace_text_that_occurs_exactly_once(tmp_path):
    from ta_bench.candidate.materialize import apply_changes
    normal = tmp_path / 'normal'
    (normal / 'ta').mkdir(parents=True)
    (normal / 'ta/entry.c').write_text('int a(void)\n{\n    return 1;\n}\nint b(void)\n{\n    return 1;\n}\n')
    change = {'path': 'ta/entry.c', 'defect': 'D1',
              'old': 'int b(void)\n{\n    return 1;', 'new': 'int b(void)\n{\n    return 2;'}
    assert apply_changes(normal, [change]) == (
        {'ta/entry.c': 'int a(void)\n{\n    return 1;\n}\nint b(void)\n{\n    return 2;\n}\n'},
        {'ta/entry.c': ['D1']})
    for bad, message in [
            ({**change, 'old': '    return 1;'}, 'found 2 times'),
            ({**change, 'old': 'missing'}, 'found 0 times'),
            ({**change, 'path': 'Makefile'}, 'forbidden replacement path'),
            ({**change, 'new': change['old']}, 'differ from new'),
            ({'path': 'ta/entry.c', 'old': 'x', 'new': 'y'}, 'requires exactly path, old, new, defect')]:
        with pytest.raises(ValidationError, match=message):
            apply_changes(normal, [bad])
    with pytest.raises(ValidationError, match='overlaps'):
        apply_changes(normal, [change, {'path': 'ta/entry.c', 'defect': 'D1',
                                        'old': 'int b(void)\n{\n', 'new': 'int b(int x)\n{\n'}])


def test_edits_belong_to_the_defect_whose_change_touches_them(tmp_path):
    from ta_bench.candidate.materialize import apply_changes, assign_edits
    normal = _tree(tmp_path / 'normal', 'int a(void)\n{\n    return 1;\n}\nint b(void)\n{\n    return 1;\n}\n')

    def change(old, new, defect='D1'):
        return {'path': 'ta/entry.c', 'defect': defect, 'old': old, 'new': new}

    # One change may come out of the line diff as several edits; all are the change's defect.
    two_places = change('int a(void)\n{\n    return 1;\n}\nint b(void)\n', 'int a(int x)\n{\n    return 1;\n}\nint b(int x)\n')
    files, owners = apply_changes(normal, [two_places])
    assert owners == {'ta/entry.c': ['D1', 'D1']}
    edits = compute_edits(normal, _tree(tmp_path / 'two', files['ta/entry.c']))
    assert assign_edits([{'id': 'D1'}], edits, owners) == [{'id': 'D1', 'edits': ['E1', 'E2']}]
    with pytest.raises(ValidationError, match='leave edits out'):
        assign_edits([{'id': 'D1', 'edits': ['E1']}], edits, owners)
    with pytest.raises(ValidationError, match='not in defects: D1'):
        assign_edits([{'id': 'D2'}], edits, owners)
    # Changes of two defects, with an unchanged line between them.
    separate = [change('int b(void)\n', 'int b(int x)\n', 'D2'), change('int a(void)\n', 'int a(int x)\n')]
    files, owners = apply_changes(normal, separate)
    assert owners == {'ta/entry.c': ['D1', 'D2']}
    edits = compute_edits(normal, _tree(tmp_path / 'separate', files['ta/entry.c']))
    assert assign_edits([{'id': 'D1'}, {'id': 'D2'}], edits, owners) == [
        {'id': 'D1', 'edits': ['E1']}, {'id': 'D2', 'edits': ['E2']}]
    # Changes of two defects on neighboring lines are one edit, which cannot belong to both.
    with pytest.raises(ValidationError, match='changes of D1, D2 in ta/entry.c share an edit'):
        apply_changes(normal, [change('int a(void)\n{\n    return 1;\n}\n', 'int a(void)\n{\n    return 1;\n} \n'),
                               change('int b(void)\n', 'int b(int x)\n', 'D2')])


@pytest.mark.parametrize('left,right', [
    (('a();\n', 'changed_a();\n'), ('c();\n', 'changed_c();\n')),
    (('a();\n', ''), ('c();\n', 'changed_c();\n')),
    (('a();\n', 'changed_a();\n'), ('c();\n', '')),
    (('a();\n', 'a();\ninsert_a();\n'), ('c();\n', 'changed_c();\n')),
    (('a();\n', 'changed_a();\n'), ('c();\n', 'insert_c();\nc();\n')),
    (('a();\na2();\n', 'a2();\na();\n'), ('c();\n', 'changed_c();\n')),
], ids=['replace', 'delete_left', 'delete_right', 'insert_left', 'insert_right', 'move'])
@pytest.mark.parametrize('context_side', ['left', 'right'])
def test_unchanged_context_does_not_change_edit_ownership(tmp_path, left, right, context_side):
    from ta_bench.candidate.materialize import apply_changes
    prefix, middle, suffix = 'void f(void)\n{\n', 'keep();\n', '}\n'
    normal = _tree(tmp_path / 'normal', prefix + left[0] + middle + right[0] + suffix)
    changes = [{'path': 'ta/entry.c', 'old': old, 'new': new, 'defect': defect}
               for (old, new), defect in [(left, 'D1'), (right, 'D2')]]
    expected = ({'ta/entry.c': prefix + left[1] + middle + right[1] + suffix},
                {'ta/entry.c': ['D1', 'D2']})
    assert apply_changes(normal, changes) == expected
    # The same source and two edits, with the unchanged separator used as matching context.
    for key in ('old', 'new'):
        if context_side == 'left':
            changes[0][key] += middle
        else:
            changes[1][key] = middle + changes[1][key]
    assert apply_changes(normal, changes) == expected


def test_a_check_moved_and_rewritten_is_two_edits_of_one_defect(tmp_path):
    from ta_bench.candidate.materialize import apply_changes
    before = 'int f(int *shared)\n{\n    int local = *shared;\n    if (local > 8)\n        return -1;\n    return local;\n}\n'
    normal = _tree(tmp_path / 'normal', before)
    files, owners = apply_changes(normal, [{
        'path': 'ta/entry.c', 'defect': 'D1',
        'old': '    int local = *shared;\n    if (local > 8)\n        return -1;\n',
        'new': '    if (*shared > 8)\n        return -1;\n    int local = *shared;\n'}])
    assert owners == {'ta/entry.c': ['D1', 'D1']}
    assert [e['kind'] for e in compute_edits(normal, _tree(tmp_path / 'moved', files['ta/entry.c']))] == ['insert', 'delete']


def _tree(root, text):
    (root / 'ta').mkdir(parents=True)
    (root / 'ta/entry.c').write_text(text)
    return root


def test_moved_lines_are_one_edit_and_revert_together(tmp_path):
    from ta_bench.candidate.diff import revert_edits
    from ta_bench.candidate.materialize import apply_changes
    before = 'int f(int x)\n{\n    copy(x);\n    if (x > 8)\n        return -1;\n    use(x);\n    return 0;\n}\n'
    after = 'int f(int x)\n{\n    if (x > 8)\n        return -1;\n    copy(x);\n    use(x);\n    return 0;\n}\n'
    normal, moved = _tree(tmp_path / 'normal', before), _tree(tmp_path / 'moved', after)
    assert compute_edits(normal, moved) == [{'edit_id': 'E1', 'path': 'ta/entry.c', 'kind': 'move',
                                             'normal_lines': [3, 3], 'defective_lines': [5, 5]}]
    revert_edits(normal, moved, tmp_path / 'reverted', ['E1'])
    assert (tmp_path / 'reverted/ta/entry.c').read_text() == before
    swap = {'path': 'ta/entry.c', 'defect': 'D1', 'old': '    copy(x);\n    if (x > 8)\n        return -1;\n',
            'new': '    if (x > 8)\n        return -1;\n    copy(x);\n'}
    assert apply_changes(normal, [swap]) == ({'ta/entry.c': after}, {'ta/entry.c': ['D1']})
    # A move with a later, separate edit keeps the numbering by first position.
    both = _tree(tmp_path / 'both', after.replace('return 0;', 'return 1;'))
    assert [(e['edit_id'], e['kind']) for e in compute_edits(normal, both)] == [('E1', 'move'), ('E2', 'replace')]
    revert_edits(normal, both, tmp_path / 'only_move', ['E1'])
    assert (tmp_path / 'only_move/ta/entry.c').read_text() == before.replace('return 0;', 'return 1;')
    # Lines that are also modified while moving stay separate edits.
    changed = _tree(tmp_path / 'changed', after.replace('    copy(x);', '    copy(x + 1);'))
    assert len(compute_edits(normal, changed)) == 2


def test_same_edit_elsewhere_or_in_another_ta_is_not_a_duplicate(tmp_path):
    text = 'int a(int x)\n{\n    use(x);\n    return 0;\n}\nint b(int y)\n{\n    use(y);\n    return 0;\n}\n'
    in_a = text.replace('    use(x);\n', '    reset(x);\n    use(x);\n')
    in_b = text.replace('    use(y);\n', '    reset(y);\n    use(y);\n')
    benchmark = tmp_path / 'benchmark'
    normal = _tree(benchmark / 'normal/one', text)
    other = _tree(benchmark / 'normal/two', '/* other TA */\n' + text)

    def at(function, line):
        return [{'detector_targets': [{'path': 'ta/entry.c', 'function': function, 'lines': [line, line]}]}]

    def save(name, normal_tree, source_text):
        case = benchmark / 'defective' / name
        _tree(case / 'source', source_text)
        atomic_json(case / 'labels.json', {'normal': {'path': 'normal/' + normal_tree.name,
                                                      'source_digest': source_digest(normal_tree)}, 'defects': at('a', 3)})

    save('case_other', other, '/* other TA */\n' + in_a.replace('reset(x)', 'clear(x)'))
    check_duplicates(normal, _tree(tmp_path / 'c1', in_a), at('a', 3), benchmark / 'defective')
    save('case_a', normal, in_a)
    check_duplicates(normal, _tree(tmp_path / 'c2', in_b), at('b', 9), benchmark / 'defective')
    with pytest.raises(ValidationError, match='duplicate normalized patch: case_a'):
        check_duplicates(normal, _tree(tmp_path / 'c3', in_a.replace('reset(x)', 'clear(x)')), at('a', 4),
                         benchmark / 'defective')


def test_a_move_saved_as_two_edits_stays_valid_and_reverts_as_saved(tmp_path):
    from ta_bench.candidate.diff import revert_edits, saved_before_moves
    before = 'int f(int x)\n{\n    copy(x);\n    if (x > 8)\n        return -1;\n    use(x);\n    return 0;\n}\n'
    after = 'int f(int x)\n{\n    if (x > 8)\n        return -1;\n    copy(x);\n    use(x);\n    return 0;\n}\n'
    normal, moved = _tree(tmp_path / 'normal', before), _tree(tmp_path / 'moved', after)
    old = compute_edits(normal, moved, moves=False)
    assert [(e['edit_id'], e['kind']) for e in old] == [('E1', 'delete'), ('E2', 'insert')]
    saved = [{'id': 'D1', 'class': 'IVW', 'edits': old, 'witness_test_ids': ['T02'], 'reason': 'order',
              'detector_targets': [{'path': 'ta/entry.c', 'function': 'f', 'lines': [5, 5], 'role': 'effect'}]}]
    assert saved_before_moves(normal, moved, saved)
    assert check_candidate(normal, moved, saved, CLASSES)[0]['edits'] == old
    revert_edits(normal, moved, tmp_path / 'half', ['E1'], moves=False)
    assert (tmp_path / 'half/ta/entry.c').read_text().count('copy(x);') == 2
    # New candidates name edits by ID and get the move as one edit.
    new = [{**saved[0], 'edits': ['E1']}]
    assert not saved_before_moves(normal, moved, new)
    assert check_candidate(normal, moved, new, CLASSES)[0]['edits'][0]['kind'] == 'move'
    with pytest.raises(ValidationError, match='unknown edit'):
        check_candidate(normal, moved, [{**saved[0], 'edits': ['E1', 'E2']}], CLASSES)


def test_same_report_position_repeats_a_case_only_when_the_same_lines_are_edited(tmp_path):
    text = ('int get(int x)\n{\n    if (x < 0)\n        return -1;\n    if (x >= 8)\n        return -1;\n'
            '    return values[x];\n}\n')
    no_lower = text.replace('    if (x < 0)\n        return -1;\n', '')
    no_upper = text.replace('    if (x >= 8)\n        return -1;\n', '')
    weak_upper = text.replace('x >= 8', 'x > 8')
    benchmark = tmp_path / 'benchmark'
    normal = _tree(benchmark / 'normal/one', text)

    def use(line):
        return [{'detector_targets': [{'path': 'ta/entry.c', 'function': 'get', 'lines': [line, line]}]}]

    case = benchmark / 'defective/case_lower'
    _tree(case / 'source', no_lower)
    atomic_json(case / 'labels.json', {'normal': {'path': 'normal/one', 'source_digest': source_digest(normal)},
                                       'defects': use(5)})
    check_duplicates(normal, _tree(tmp_path / 'upper', no_upper), use(5), benchmark / 'defective')
    case = benchmark / 'defective/case_upper'
    _tree(case / 'source', weak_upper)
    atomic_json(case / 'labels.json', {'normal': {'path': 'normal/one', 'source_digest': source_digest(normal)},
                                       'defects': use(7)})
    with pytest.raises(ValidationError, match='duplicate detector targets: case_upper'):
        check_duplicates(normal, _tree(tmp_path / 'weaker', text.replace('x >= 8', 'x >= 9 + 1')), use(7),
                         benchmark / 'defective')
