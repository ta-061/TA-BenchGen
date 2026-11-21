import copy
import re
import shutil
from pathlib import Path

import pytest

from ta_bench.candidate.diff import compute_diff, compute_edits
from ta_bench.common.jsonio import atomic_json, canonical_hash, load_json
from ta_bench.common.sources import source_digest
from ta_bench.dataset import reviews
from ta_bench.dataset.store import inspect_case, save_case
from ta_bench.review.app import _comparison_rows, create_app
from ta_bench.review.blind_export import export_blind
from ta_bench.review.source_diff import compare_sources

CLASSES = {"IVW": {"description": "外部入力の検証不足", "supported": True}}


@pytest.fixture
def case(tmp_path):
    benchmark = tmp_path / "benchmark"
    normal = benchmark / "normal" / "sample"
    (normal / "ta").mkdir(parents=True)
    (normal / "host").mkdir()
    (normal / "ta" / "entry.c").write_text("int read_item(int index)\n{\n    if (index > 3)\n        return -1;\n    return index;\n}\n")
    (normal / "host" / "main.c").write_text("int main(void) { return 0; }\n")
    defective = tmp_path / "candidate"
    shutil.copytree(normal, defective)
    (defective / "ta" / "entry.c").write_text("int read_item(int index)\n{\n    return index;\n}\n")
    case_id = "case_0123456789abcdef"
    labels = {"schema_version": "4.0", "case_id": case_id,
              "normal": {"path": "normal/sample", "source_digest": source_digest(normal)},
              "defects": [{"id": "D1", "class": "IVW", "reason": "境界の確認がなくなる",
                           "edits": compute_edits(normal, defective),
                           "detector_targets": [{"path": "ta/entry.c", "function": "read_item", "lines": [3, 3], "role": "effect"}],
                           "witness_test_ids": ["T02"]}],
              "review": {"status": "unreviewed", "reviews": [], "approved_against": None}}
    steps = [{"op": "open", "session": "s1"}, {"op": "invoke", "session": "s1", "command_id": 0,
             "params": [{"type": "value_input", "a": 4, "b": 0}, {"type": "none"}, {"type": "none"}, {"type": "none"}]}, {"op": "close", "session": "s1"}]
    observations = [{"op": step["op"], "result": 0, "origin": 0, "params": [], "ta_crashed": False} for step in steps]
    tests = [{"id": "T01", "purpose": "normal", "targets": [], "steps": copy.deepcopy(steps), "observed": {"normal": copy.deepcopy(observations), "defective": copy.deepcopy(observations)}, "equal": True},
             {"id": "T02", "purpose": "witness", "targets": ["D1"], "witness_step": 2, "steps": copy.deepcopy(steps), "observed": {"normal": copy.deepcopy(observations), "defective": copy.deepcopy(observations)}, "equal": False}]
    tests[1]["observed"]["normal"][1]["result"] = 1
    verification = {"schema_version": "4.0", "case_id": case_id,
                    "environment": {"optee_revision": "test", "qemu_revision": "test", "toolchain": "test", "image_digest": "sha256:" + "a" * 64, "runner_version": "test"},
                    "generation": {"model_id": "test", "attempt_index": 1, "attempts_total": 1, "plan_digest": canonical_hash([{k: v for k, v in t.items() if k not in {'observed', 'equal'}} for t in tests])},
                    "semantic": {"tests": tests,
                                 "machine_validation": {"status": "machine_pass", "per_defect": {"D1": "machine_pass"}, "repetitions": 2}},
                    "run_meta": {"verified_at": "2026-01-01T00:00:00Z", "run_id": "test"}}
    path = save_case(benchmark / "defective", defective, labels, verification, compute_diff(normal, defective))
    work = tmp_path / "work"
    app = create_app(benchmark, CLASSES, work)
    app.config["TESTING"] = True
    return benchmark, path, work, app


def post(app, case_id, reviewer="A", action="approve", checks=None, reason=""):
    page = app.test_client().get(f"/cases/{case_id}").text
    match = re.search(r'name="expected_against" value="([^"]+)"', page)
    expected = match.group(1) if match else "invalid"
    return app.test_client().post(f"/cases/{case_id}/review", json={"csrf_token": app.config["CSRF_TOKEN"], "expected_against": expected,
           "reviewer": reviewer, "action": action, "checks": checks if checks is not None else {"D1": {"class": True, "location": True, "behavior": True}}, "reason": reason})


def test_readonly_launch_and_views(case):
    _benchmark, path, work, app = case
    before = (path / "labels.json").read_bytes()
    assert app.test_client().get("/").status_code == 200
    response = app.test_client().get(f"/cases/{path.name}")
    assert response.status_code == 200
    assert "入力と観測" in response.text
    assert "read_item" in response.text
    assert 'class="source-gap right"' in response.text  # lines deleted from the normal version
    locations = re.findall(r'class="source-location" href="#([^"]+)"', response.text)
    assert any(link.endswith("-left-3") for link in locations)  # removed edit
    assert any(link.endswith("-right-3") for link in locations)  # target on the following unchanged line
    assert all(f'id="{link}"' in response.text for link in locations)
    assert 'D1 · 影響操作' in response.text and '保護操作なし' in response.text
    assert (path / "labels.json").read_bytes() == before
    assert not work.exists()


def test_source_comparison_aligns_both_line_numbers_across_changes(tmp_path):
    normal, defective = tmp_path / "normal", tmp_path / "defective"
    for root in (normal, defective):
        root.mkdir()
        (root / "a.h").write_text("same\n")
    (normal / "b.c").write_text("head\nremoved\nanchor\nold A\nold B\nseam\nend\n")
    (defective / "b.c").write_text("head\nanchor\nnew A\nseam\nadded A\nadded B\nend\n")

    files = compare_sources(normal, defective)
    assert list(files) == ["b.c", "a.h"]
    assert files["a.h"]["removed"] == files["a.h"]["added"] == 0
    file = files["b.c"]
    assert file["removed"] == file["added"] == 3
    assert sum(block["changed"] for block in file["blocks"]) == 3
    pairs = [(old and old[0], new and new[0]) for block in file["blocks"] for old, new in block["rows"]]
    assert pairs == [(1, 1), (2, None), (3, 2), (4, 3), (5, None), (6, 4),
                     (None, 5), (None, 6), (7, 7)]


def test_approval_checks_and_stale(case):
    benchmark, path, _work, app = case
    original = (path / "labels.json").read_bytes()
    incomplete = {"D1": {"class": True, "location": True, "behavior": False}}
    assert post(app, path.name, checks=incomplete).status_code == 400
    assert load_json(path / "labels.json")["review"]["status"] == "unreviewed"
    assert post(app, path.name, action="save", checks=incomplete).status_code == 200
    assert (path / "labels.json").read_bytes() == original
    assert load_json(path / "label_history.json")["review"]["reviews"][0]["checks"] == incomplete
    assert post(app, path.name).json["status"] == "approved"
    assert load_json(path / "labels.json")["review"] == {"status": "approved"}
    assert inspect_case(path, benchmark, CLASSES)["status"] == "approved"
    verification = load_json(path / "verification.json")
    verification["run_meta"]["verified_at"] = "2026-03-01T00:00:00Z"
    atomic_json(path / "verification.json", verification)
    assert inspect_case(path, benchmark, CLASSES)["status"] == "approved"
    labels = load_json(path / "labels.json")
    labels["defects"][0]["reason"] += "。確認用の補足"
    atomic_json(path / "labels.json", labels)
    assert inspect_case(path, benchmark, CLASSES)["status"] == "stale"
    detail = app.test_client().get(f"/cases/{path.name}?reviewer=A")
    assert b'checked' not in detail.data
    assert post(app, path.name).json["status"] == "approved"


def test_multiple_reviewers_and_rejection(case):
    benchmark, path, work, _ = case
    app = create_app(benchmark, CLASSES, work, required_reviewers=2)
    assert post(app, path.name, reviewer="A").json["status"] == "in_review"
    assert load_json(path / "labels.json")["review"] == {"status": "unreviewed"}
    assert post(app, path.name, reviewer="A").json["status"] == "in_review"
    assert post(app, path.name, reviewer="B").json["status"] == "approved"
    assert post(app, path.name, reviewer="B", action="reject").status_code == 400
    assert post(app, path.name, reviewer="B", action="reject", reason="分類が異なる").json["status"] == "rejected"
    assert load_json(path / "labels.json")["review"] == {"status": "unreviewed"}
    review = load_json(path / "label_history.json")["review"]
    assert review["reviews"][-1]["reason"] == "分類が異なる"
    assert review["approved_against"] is None
    assert "分類が異なる" in app.test_client().get(f"/cases/{path.name}").text


def test_request_protection_and_broken_case(case):
    _benchmark, path, _work, app = case
    client = app.test_client()
    url = f"/cases/{path.name}/review"
    assert client.post(url, json={"action": "approve"}).status_code == 403
    assert client.post(url, json={"csrf_token": app.config["CSRF_TOKEN"]}, headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.test"}).status_code == 403
    assert client.get("/", environ_base={"REMOTE_ADDR": "192.168.1.2"}).status_code == 403
    (path / "changes.diff").write_text("incorrect")
    assert post(app, path.name).status_code == 409
    assert client.get(f"/cases/{path.name}").status_code == 200


def test_lan_sharing_accepts_private_clients_by_address_only(case):
    benchmark, path, work, local = case
    assert "</a> LOCALHOST</span>" in local.test_client().get("/").text
    app = create_app(benchmark, CLASSES, work, lan=True)
    client = app.test_client()

    def get(remote, host="192.168.1.10:8765"):
        return client.get("/", headers={"Host": host}, environ_base={"REMOTE_ADDR": remote})
    for remote in ["192.168.1.2", "10.20.30.40", "172.31.255.1", "169.254.7.7", "fd00::2", "fe80::2%eth0",
                   "::ffff:192.168.1.2", "127.0.0.1", "::ffff:127.0.0.1"]:
        assert get(remote).status_code == 200, remote
    for remote in ["8.8.8.8", "172.32.0.1", "100.64.0.1", "2001:4860:4860::8888", "::ffff:8.8.8.8", "unknown"]:
        assert get(remote).status_code == 403, remote
    assert get("192.168.1.2", host="[fd00::1]:8765").status_code == 200
    assert get("192.168.1.2", host="review.evil.test:8765").status_code == 403  # DNS can point a name here
    assert "</a> LAN</span>" in get("192.168.1.2").text

    # A review is saved from the network under the same CSRF and origin checks.
    def send(method, url, origin="http://192.168.1.10:8765", **options):
        return method(url, headers={"Host": "192.168.1.10:8765", "Origin": origin},
                      environ_base={"REMOTE_ADDR": "192.168.1.2"}, **options)
    detail = send(client.get, f"/cases/{path.name}").text
    review = {"expected_against": re.search(r'name="expected_against" value="([^"]+)"', detail).group(1),
              "reviewer": "B", "action": "approve", "checks": {"D1": {"class": True, "location": True, "behavior": True}}}
    signed = {**review, "csrf_token": app.config["CSRF_TOKEN"]}
    url = f"/cases/{path.name}/review"
    assert send(client.post, url, json=review).status_code == 403
    assert send(client.post, url, origin="http://evil.test", json=signed).status_code == 403
    assert load_json(path / "labels.json")["review"]["status"] == "unreviewed"
    assert send(client.post, url, json=signed).json["status"] == "approved"


def test_page_loads_wait_for_a_save_in_progress(case, monkeypatch):
    """A shared server answers in threads; a half-written save must not read as a damaged case."""
    import threading

    _benchmark, path, _work, app = case
    pages, write = [], reviews.atomic_json

    def slow_save(target, value):
        partial = target.parent / ".labels.json.partial"  # what the directory holds midway through a save
        partial.write_text("")
        reader = threading.Thread(target=lambda: pages.append(app.test_client().get(f"/cases/{path.name}").text))
        reader.start()
        reader.join(timeout=0.3)
        partial.unlink()
        write(target, value)
        readers.append(reader)
    readers = []
    monkeypatch.setattr(reviews, "atomic_json", slow_save)
    assert post(app, path.name, action="save").status_code == 200
    readers[0].join(timeout=10)
    assert len(pages) == 1 and 'id="review-form"' in pages[0]


def test_review_command_shares_on_the_network_only_when_asked(case, tmp_path, monkeypatch, capsys):
    from flask import Flask

    from ta_bench.cli import main
    benchmark, _path, work, _app = case
    config = tmp_path / "classes.yaml"
    config.write_text("classes:\n  IVW:\n    description: Missing range check.\n    supported: true\n")
    served = []
    monkeypatch.setattr(Flask, "run", lambda app, **options: served.append((app, options)))
    arguments = ["review", "--dir", str(benchmark), "--work-dir", str(work), "--classes", str(config)]
    neighbor = {"headers": {"Host": "192.168.1.10:8765"}, "environ_base": {"REMOTE_ADDR": "192.168.1.2"}}

    assert main(arguments) == 0
    app, options = served[-1]
    assert (options["host"], options["threaded"]) == ("127.0.0.1", False)
    assert app.test_client().get("/", **neighbor).status_code == 403
    assert "LAN" not in capsys.readouterr().out

    assert main([*arguments, "--host", "0.0.0.0"]) == 0
    app, options = served[-1]
    assert (options["host"], options["threaded"]) == ("0.0.0.0", True)
    assert app.test_client().get("/", **neighbor).status_code == 200
    assert "LAN内に公開" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        main([*arguments, "--host", "review.example"])


def test_export_blind_source_only_and_private_mapping(case, tmp_path):
    benchmark, path, work, app = case
    with pytest.raises(ValueError, match="eligible"):
        export_blind(benchmark, tmp_path / "empty-export", CLASSES, work)
    assert post(app, path.name).status_code == 200
    destination = tmp_path / "evaluation-input"
    result = export_blind(benchmark, destination, CLASSES, work)
    assert result["count"] == 1
    exported = list(destination.iterdir())
    assert len(exported) == 1 and exported[0].name != path.name
    files = [p.relative_to(exported[0]).as_posix() for p in exported[0].rglob("*") if p.is_file()]
    assert files == ["ta/entry.c"]
    mapping_path = Path(result["mapping_path"])
    assert not mapping_path.is_relative_to(destination)
    assert load_json(mapping_path)["cases"][exported[0].name]["case_id"] == path.name
    assert mapping_path.stat().st_mode & 0o777 == 0o600
    assert inspect_case(path, benchmark, CLASSES)["status"] == "approved"
    with pytest.raises(ValueError, match="already exists"):
        export_blind(benchmark, destination, CLASSES, work)


def test_export_rejects_nested_destinations_and_stale(case, tmp_path):
    benchmark, path, work, app = case
    for destination in [benchmark / "output", work / "output"]:
        with pytest.raises(ValueError):
            export_blind(benchmark, destination, CLASSES, work, approved_only=False)
    post(app, path.name)
    labels = load_json(path / "labels.json")
    labels["defects"][0]["reason"] += " changed"
    atomic_json(path / "labels.json", labels)
    with pytest.raises(ValueError, match="eligible"):
        export_blind(benchmark, tmp_path / "stale-export", CLASSES, work, approved_only=False)


def test_form_buttons_work_without_javascript(case):
    benchmark, path, _work, app = case
    response = app.test_client().post(f"/cases/{path.name}/review", data={"csrf_token": app.config["CSRF_TOKEN"], "expected_against": canonical_hash(inspect_case(path, benchmark, CLASSES)["hashes"]), "reviewer": "フォーム評価者", "action": "approve", "D1.class": "on", "D1.location": "on", "D1.behavior": "on"})
    assert response.status_code == 303
    assert inspect_case(path, benchmark, CLASSES)["status"] == "approved"


def test_malformed_records_remain_visible(case):
    _benchmark, path, _work, app = case
    atomic_json(path / "labels.json", ["not a labels object"])
    assert app.test_client().get("/").status_code == 200
    response = app.test_client().get(f"/cases/{path.name}")
    assert response.status_code == 200
    assert "整合性の確認が必要です" in response.text
    assert post(app, path.name).status_code == 409


def test_changed_case_cannot_be_approved_from_old_page(case):
    benchmark, path, _work, app = case
    expected = canonical_hash(inspect_case(path, benchmark, CLASSES)["hashes"])
    labels = load_json(path / "labels.json")
    labels["defects"][0]["reason"] += " 追記"
    atomic_json(path / "labels.json", labels)
    response = app.test_client().post(f"/cases/{path.name}/review", json={
        "csrf_token": app.config["CSRF_TOKEN"], "expected_against": expected,
        "reviewer": "A", "action": "approve",
        "checks": {"D1": {"class": True, "location": True, "behavior": True}},
    })
    assert response.status_code == 409
    assert load_json(path / "labels.json")["review"]["status"] == "unreviewed"


def test_review_names_the_items_left_out_of_the_comparison(case):
    _, path, _, app = case
    page = app.test_client().get(f"/cases/{path.name}").get_data(as_text=True)
    assert "比較から除外した項目" in page
    row = {"op": "invoke", "result": 0, "origin": 0, "ta_crashed": False,
           "params": [{"type": "memref_output", "size": 8, "data": "0200000024750000"}]}
    again = copy.deepcopy(row)
    again["params"][0]["data"] = "020000001f750000"
    defective = {**copy.deepcopy(row), "result": 1, "params": [{"type": "memref_output", "size": 8, "data": "01000000"}]}
    rows = _comparison_rows({"steps": [{"op": "invoke"}], "observed": {"normal": [row], "defective": [defective]},
                             "repeated_observed": {"normal": [again], "defective": [defective]}})
    assert rows[0]["variable"] == ["引数 0 のデータ"]
    assert rows[0]["normal"]["params"][0] == {"type": "memref_output", "size": 8, "data": "**"}
    assert rows[0]["different"] is True


def test_screen_switches_between_japanese_and_english(case, tmp_path):
    from ta_bench.common.classes import japanese_descriptions
    benchmark, path, work, _ = case
    config = tmp_path / "classes.yaml"
    config.write_text("classes:\n  IVW:\n    # 範囲検査の欠落\n    description: Missing range check.\n    supported: true\n")
    assert japanese_descriptions(config) == {"IVW": "範囲検査の欠落"}
    classes = {"IVW": {"description": "Missing range check.", "supported": True}}
    client = create_app(benchmark, classes, work, descriptions_ja=japanese_descriptions(config)).test_client()
    japanese = client.get(f"/cases/{path.name}").get_data(as_text=True)
    assert "分類の定義" in japanese and "範囲検査の欠落" in japanese and ">English</a>" in japanese
    english = client.get(f"/cases/{path.name}?lang=en").get_data(as_text=True)
    assert "Class definition" in english and "Missing range check." in english and ">日本語</a>" in english
    # Only stored data (the defect's own reason) and the switch itself remain Japanese.
    assert not re.search("[ぁ-んァ-ヶ]", english.replace("日本語", "").replace("境界の確認がなくなる", ""))
    assert "Cases to review" in client.get("/").get_data(as_text=True)  # remembered in a cookie
    assert "レビュー対象" in client.get("/?lang=ja").get_data(as_text=True)


@pytest.fixture
def two_defects(case):
    benchmark, path, _, _ = case
    normal = benchmark / "normal" / "sample"
    for root, value in [(normal, 1), (path / "source", 2)]:
        (root / "ta" / "value.c").write_text(f"int value(void)\n{{\n    return {value};\n}}\n")
    labels, verification = (load_json(path / name) for name in ("labels.json", "verification.json"))
    edits = compute_edits(normal, path / "source")
    d1, = labels["defects"]
    d1["edits"] = [edits[0]]
    d2 = {**d1, "id": "D2", "edits": [edits[1]], "witness_test_ids": ["T03"],
          "detector_targets": [{"path": "ta/value.c", "function": "value", "lines": [2, 3], "role": "effect"}]}
    labels["defects"].append(d2)
    labels["normal"]["source_digest"] = source_digest(normal)
    semantic = verification["semantic"]
    semantic["tests"].append({**copy.deepcopy(semantic["tests"][1]), "id": "T03", "targets": ["D2"]})
    semantic["machine_validation"]["per_defect"]["D2"] = "machine_pass"
    semantic["defect_reverts"] = [{"defect_id": d["id"], "witness_matches_normal_after_revert": True} for d in (d1, d2)]
    verification["generation"]["plan_digest"] = canonical_hash([
        {k: v for k, v in t.items() if k not in {"observed", "equal"}} for t in semantic["tests"]])
    atomic_json(path / "labels.json", labels)
    atomic_json(path / "verification.json", verification)
    (path / "changes.diff").write_text(compute_diff(normal, path / "source"))
    assert inspect_case(path, benchmark, CLASSES)["warnings"] == []
    return case


def scoped(case, did, action, reviewer="A", **kwargs):
    benchmark, path, _, app = case
    version = inspect_case(path, benchmark, CLASSES)["defect_versions"][did]
    return app.test_client().post(f"/cases/{path.name}/defects/{did}/review", json={
        "csrf_token": app.config["CSRF_TOKEN"], "expected_against": version, "reviewer": reviewer, "action": action,
        "checks": {did: dict.fromkeys(("class", "location", "behavior"), True)}, **kwargs})


def test_independent_reviews_corrected_range_and_history(two_defects, tmp_path):
    benchmark, path, work, app = two_defects
    generated = (path / "labels.json").read_bytes()
    info = inspect_case(path, benchmark, CLASSES)
    original = info["labels"]["defects"][1]["detector_targets"][0]
    corrected = {**original, "lines": [3, 3]}
    assert scoped(two_defects, "D1", "approve").json["per_defect"] == {"D1": "approved", "D2": "unreviewed"}
    assert scoped(two_defects, "D2", "reject", reason="位置を要修正").json["status"] == "partially_approved"
    with pytest.raises(ValueError, match="eligible"):
        export_blind(benchmark, tmp_path / "partial", CLASSES, work)
    updated = scoped(two_defects, "D2", "edit", targets=[corrected], reason="該当する文に限定")
    assert updated.json["per_defect"] == {"D1": "approved", "D2": "in_review"}
    inspection = inspect_case(path, benchmark, CLASSES)
    assert inspection["warnings"] == []
    assert inspection["labels"]["defects"][1]["detector_targets"] == [corrected]
    assert inspection["labels"]["defects"][0] == info["labels"]["defects"][0]
    assert inspection["verification"] == info["verification"]
    assert (path / "labels.json").read_bytes() == generated
    draft_export = export_blind(benchmark, tmp_path / "including-drafts", CLASSES, work, approved_only=False)
    sample, = load_json(Path(draft_export["mapping_path"]))["cases"].values()
    assert sample["labels"] == load_json(path / "labels.json") and sample["against"]["labels"] == info["hashes"]["labels"]
    history = load_json(path / "label_history.json")["changes"]
    assert history == inspection["label_history"] and len(history) == 1
    assert history[0] == {"at": history[0]["at"], "reviewer": "A", "defect_id": "D2", "before": [original],
                          "after": [corrected], "reason": "該当する文に限定"}
    assert scoped(two_defects, "D2", "approve", expected_against=info["defect_versions"]["D2"]).status_code == 409
    assert scoped(two_defects, "D2", "edit", targets=[corrected]).status_code == 200
    assert load_json(path / "label_history.json")["changes"] == history
    assert scoped(two_defects, "D2", "approve").json["status"] == "approved"
    published = load_json(path / "labels.json")
    assert published["review"] == {"status": "approved"}
    assert published["defects"][1]["detector_targets"] == [corrected]
    exported = export_blind(benchmark, tmp_path / "complete", CLASSES, work)
    sample, = load_json(Path(exported["mapping_path"]))["cases"].values()
    assert sample["labels"] == published
    assert not list((tmp_path / "complete").rglob("*.json"))
    page = app.test_client().get(f"/cases/{path.name}").text
    assert "人が修正した位置" in page and "該当する文に限定" in page
    assert 'id="label-history-D2"' in page and 'id="label-history-D1"' not in page
    # Even returning to a previous range is a new revision, and only D2 needs another decision.
    result = scoped(two_defects, "D2", "edit", targets=[original], reviewer="B")
    assert result.json["per_defect"] == {"D1": "approved", "D2": "in_review"}
    assert load_json(path / "labels.json") == {**published, "review": {"status": "unreviewed"}}
    assert scoped(two_defects, "D2", "approve", expected_against=info["defect_versions"]["D2"]).status_code == 409
    assert len(inspect_case(path, benchmark, CLASSES)["label_history"]) == 2


def test_invalid_location_and_incomplete_approval_do_not_write(case):
    _, path, _, _ = case
    labels = load_json(path / "labels.json")
    original, = labels["defects"][0]["detector_targets"]
    for changes in ({"lines": [0, 1]}, {"lines": [3, 2]}, {"lines": [2, 50]}, {"lines": [True, 3]},
                    {"path": "../labels.json"}, {"path": "host/main.c"}, {"function": "absent"}):
        assert scoped(case, "D1", "edit", targets=[{**original, **changes}]).status_code == 400
    for roles in ([], ["protection"], ["effect", "effect"], ["effect", "protection", "protection"], ["other"]):
        targets = [{**original, "role": role} for role in roles]
        assert scoped(case, "D1", "edit", targets=targets).status_code == 400
    # Line 4 is the function's closing brace. An approval must not save it as a location.
    assert scoped(case, "D1", "approve", targets=[{**original, "lines": [4, 4]}]).status_code == 400
    bad_approval = scoped(case, "D1", "approve", targets=[{**original, "lines": [2, 3]}], checks={"D1": {}})
    assert bad_approval.status_code == 400
    assert load_json(path / "labels.json") == labels and not (path / "label_history.json").exists()


def test_role_locations_update_independently(case):
    benchmark, path, _, app = case
    client = app.test_client()
    url = f"/cases/{path.name}"
    effect, = load_json(path / "labels.json")["defects"][0]["detector_targets"]
    protection = {**effect, "role": "protection"}

    def submit(action, **fields):
        version = inspect_case(path, benchmark, CLASSES)["defect_versions"]["D1"]
        return client.post(url + "/defects/D1/review", data={
            "csrf_token": app.config["CSRF_TOKEN"], "D1.expected": version,
            "reviewer": "A", "action": action, **fields})

    def form(target):
        prefix = "D1." + target["role"]
        return {prefix + ".path": target["path"], prefix + ".function": target["function"],
                prefix + ".start": str(target["lines"][0]), prefix + ".end": ""}

    # Submitting the displayed locations with an ordinary decision is not a correction.
    assert submit("save", **form(effect), **{"D1.protection.path": ""}).status_code == 303
    saved = load_json(path / "label_history.json")
    assert saved["changes"] == [] and saved["review"]["reviews"][-1]["action"] == "save"
    assert submit("edit", **form(effect), **form(protection)).status_code == 303
    assert scoped(case, "D1", "approve").json["status"] == "approved"
    page = client.get(url).text
    assert "D1 · 影響操作" in page and "D1 · 保護操作" in page

    correction = {**protection, "lines": [1, 1]}
    assert submit("edit", **form(correction)).status_code == 303  # the omitted effect is kept
    history = load_json(path / "label_history.json")["changes"]
    assert history[0]["before"] == [effect] and history[0]["after"] == [effect, protection]
    assert history[1]["before"] == history[0]["after"] and history[1]["after"] == [effect, correction]
    assert scoped(case, "D1", "edit", targets=[correction, effect]).status_code == 200
    assert load_json(path / "label_history.json")["changes"] == history

    assert submit("edit", **form(effect), **{"D1.protection.path": ""}).status_code == 303
    info = inspect_case(path, benchmark, CLASSES)
    assert not info["warnings"] and info["labels"]["defects"][0]["detector_targets"] == [effect]
    assert "保護操作なし" in client.get(url).text
    assert submit("edit", **{"D1.effect.path": ""}).status_code == 400  # an effect is always required


def test_role_location_requires_code_in_the_selected_range(tmp_path):
    from ta_bench.candidate.check import validate_target
    from ta_bench.errors import ValidationError

    (tmp_path / "ta").mkdir()
    (tmp_path / "ta/value.c").write_text(
        "int value(void) {\n"
        "   \n"
        "    /* example:\n"
        "       return 1;\n"
        "    */\n"
        "    // another example: \\\n"
        "       return 2;\n"
        "    { } ; /* empty block */\n"
        "    return sizeof(\n"
        '        "/*"); // string operand\n'
        "} // end\n"
    )
    target = {"path": "ta/value.c", "function": "value", "lines": [2, 2]}
    for role in ("effect", "protection"):
        for lines in ([2, 2], [4, 4], [6, 6], [7, 7], [8, 8], [11, 11], [2, 8]):
            with pytest.raises(ValidationError, match="operation"):
                validate_target({**target, "role": role, "lines": lines}, tmp_path)
        for lines in ([10, 10], [9, 10], [8, 11]):
            validate_target({**target, "role": role, "lines": lines}, tmp_path)
    for wrong in ({**target, "role": "unsafe_use"}, {**target, "role": "effect", "note": "x"}, target):
        with pytest.raises(ValidationError, match="role"):
            validate_target(wrong, tmp_path)


def test_legacy_votes_survive_a_sibling_edit_and_require_fresh_votes_for_changed_target(two_defects):
    benchmark, path, work, _ = two_defects
    info = inspect_case(path, benchmark, CLASSES)
    labels = info["labels"]
    checks = {d["id"]: dict.fromkeys(("class", "location", "behavior"), True) for d in labels["defects"]}
    labels["review"].update(status="in_review", reviews=[
        {"reviewer": "A", "action": "approve", "checks": checks, "against": info["hashes"]}])
    legacy_vote = copy.deepcopy(labels["review"]["reviews"][0])
    atomic_json(path / "labels.json", labels)
    case = (benchmark, path, work, create_app(benchmark, CLASSES, work, required_reviewers=2))
    original = labels["defects"][1]["detector_targets"][0]
    # The old page for D1 still applies after D2 is edited.
    assert scoped(case, "D2", "approve", reviewer="B", targets=[{**original, "lines": [3, 3]}]).json["status"] == "in_review"
    assert scoped(case, "D1", "approve", reviewer="B", expected_against=info["defect_versions"]["D1"]).json[
        "per_defect"] == {"D1": "approved", "D2": "in_review"}
    assert scoped(case, "D2", "approve", reviewer="C").json["status"] == "approved"
    assert load_json(path / "label_history.json")["review"]["reviews"][0] == legacy_vote


def test_location_form_one_line_cross_file_and_audit_integrity(two_defects):
    benchmark, path, _, app = two_defects
    info = inspect_case(path, benchmark, CLASSES)
    response = app.test_client().post(f"/cases/{path.name}/defects/D1/review", data={
        "csrf_token": app.config["CSRF_TOKEN"], "D1.expected": info["defect_versions"]["D1"],
        "reviewer": "User", "action": "edit", "D1.effect.path": "ta/value.c", "D1.effect.function": "value",
        "D1.effect.start": "3", "D1.effect.end": "", "D1.reason": "呼び出し先を確認"})
    assert response.status_code == 303 and response.location.endswith("#defect-D1")
    new = inspect_case(path, benchmark, CLASSES)
    assert new["warnings"] == []
    assert new["label_history"][0]["after"] == [{"path": "ta/value.c", "function": "value", "lines": [3, 3], "role": "effect"}]
    record = load_json(path / "label_history.json")
    record["changes"][0]["after"][0]["lines"] = [1, 3]
    atomic_json(path / "label_history.json", record)
    assert "history mismatch" in " ".join(inspect_case(path, benchmark, CLASSES)["warnings"])
    assert post(app, path.name).status_code == 409


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_interrupted_correction_does_not_appear_in_review_history(case, monkeypatch, failure):
    benchmark, path, _, _ = case
    labels = inspect_case(path, benchmark, CLASSES)["labels"]
    original = labels["defects"][0]["detector_targets"][0]
    with monkeypatch.context() as patch:
        def interrupt(target, value):
            if target.name == "label_history.json":
                raise failure("interrupted before commit")
            atomic_json(target, value)
        patch.setattr(reviews, "atomic_json", interrupt)
        with pytest.raises(failure):
            scoped(case, "D1", "edit", targets=[{**original, "lines": [2, 3]}])
    info = inspect_case(path, benchmark, CLASSES)
    assert info["warnings"] == [] and info["labels"] == labels and info["label_history"] == []
    assert scoped(case, "D1", "edit", targets=[{**original, "lines": [1, 2]}]).status_code == 200
    changes = load_json(path / "label_history.json")["changes"]
    assert len(changes) == 1 and changes[0]["before"] == [original] and changes[0]["after"][0]["lines"] == [1, 2]


@pytest.mark.parametrize("committed", [False, True])
def test_interrupted_approval_keeps_matching_labels_and_history(case, monkeypatch, committed):
    benchmark, path, _, _ = case
    original, = load_json(path / "labels.json")["defects"][0]["detector_targets"]
    corrected = {**original, "lines": [2, 3]}
    assert scoped(case, "D1", "edit", targets=[corrected]).status_code == 200

    def interrupt(target, value):
        if target.name == "labels.json":
            if committed:
                atomic_json(target, value)
            raise OSError("interrupted label write")
        atomic_json(target, value)

    with monkeypatch.context() as patch:
        patch.setattr(reviews, "atomic_json", interrupt)
        with pytest.raises(OSError):
            scoped(case, "D1", "approve", reason="確認した位置")
    info = inspect_case(path, benchmark, CLASSES)
    assert info["warnings"] == []
    assert info["status"] == ("approved" if committed else "in_review")
    assert info["labels"]["defects"][0]["detector_targets"] == [corrected]
    assert load_json(path / "labels.json")["defects"][0]["detector_targets"] == [corrected if committed else original]
    if not committed:
        assert scoped(case, "D1", "approve", reason="確認した位置").status_code == 200
    else:
        reviews.publish_review(path, info["labels"], info["label_history"])
    history = load_json(path / "label_history.json")
    assert "pending" not in history and [v["action"] for v in history["review"]["reviews"]] == ["edit", "approve"]


def test_move_existing_approval_to_history_without_another_vote(case):
    benchmark, path, _, app = case
    original, = load_json(path / "labels.json")["defects"][0]["detector_targets"]
    assert scoped(case, "D1", "edit", targets=[{**original, "lines": [2, 3]}]).status_code == 200
    assert scoped(case, "D1", "save").status_code == 200
    assert scoped(case, "D1", "approve", reason="位置を確認しました").status_code == 200
    existing = inspect_case(path, benchmark, CLASSES)
    # Rebuild the previously stored form: decisions in labels, only corrections in the history.
    atomic_json(path / "labels.json", existing["labels"])
    atomic_json(path / "label_history.json", {"case_id": path.name, "changes": existing["label_history"]})
    before = inspect_case(path, benchmark, CLASSES)
    reviews.publish_review(path, before["labels"], before["label_history"])
    after = inspect_case(path, benchmark, CLASSES)
    assert before["status"] == after["status"] == "approved" and after["warnings"] == []
    assert before["labels"] == after["labels"] and before["hashes"] == after["hashes"]
    assert before["label_history"] == after["label_history"] and before["defect_versions"] == after["defect_versions"]
    assert load_json(path / "labels.json")["review"] == {"status": "approved"}
    assert "位置を確認しました" in app.test_client().get(f"/cases/{path.name}").text
    (path / "label_history.json").unlink()
    assert inspect_case(path, benchmark, CLASSES)["status"] == "invalid"
    assert post(app, path.name).status_code == 409


def test_blind_snapshot_catches_changed_individual_decisions(two_defects, tmp_path, monkeypatch):
    benchmark, _, work, _ = two_defects
    assert scoped(two_defects, "D1", "approve").json["status"] == "partially_approved"
    copy_file = shutil.copyfile

    def copy_then_review(source, destination):
        result = copy_file(source, destination)
        if source.name == "entry.c":
            scoped(two_defects, "D1", "reject", reason="再確認")
            assert scoped(two_defects, "D2", "approve").json["status"] == "partially_approved"
        return result

    monkeypatch.setattr(shutil, "copyfile", copy_then_review)
    destination = tmp_path / "export"
    with pytest.raises(ValueError, match="changed while exporting"):
        export_blind(benchmark, destination, CLASSES, work, approved_only=False)
    assert not destination.exists()
