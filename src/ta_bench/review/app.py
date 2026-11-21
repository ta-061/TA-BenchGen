"""Human review. Reading cases never generates candidates or invokes a runner."""
from __future__ import annotations

import fcntl
import ipaddress
import secrets
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from flask import Flask, abort, redirect, render_template, request, url_for

from ..candidate.check import TARGET_ROLES, validate_target, validate_target_roles
from ..common.jsonio import canonical_hash
from ..dataset.layout import blocking_warnings
from ..dataset.reviews import CHECKS, latest_reviews, publish_review
from ..dataset.schema import CASE_ID
from ..dataset.store import inspect_case
from ..runtime.observations import comparison
from .cases import case_paths, reviewable
from .decisions import record_decision
from .source_diff import compare_sources, source_annotations
from .texts import LANGUAGES, STATUS_LABELS, translate

ACTIONS = {"save", "approve", "reject", "edit"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
LOCAL_ADDRESSES = {None, "127.0.0.1", "::1"}
# Clients of a server shared on the local network: this machine, private and link-local addresses.
LAN_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10"))
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                           "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
UNKNOWN = "不明"


def _address(text):
    """The IP address that text spells out, or None for a name. An IPv4 client of an IPv6 socket is IPv4."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    return getattr(address, "ipv4_mapped", None) or address


def _on_lan(client) -> bool:
    address = _address(client)
    return address is not None and any(address in network for network in LAN_NETWORKS)


def _japanese(text, **values):
    return translate('ja', text, **values)


def _item_label(item: dict, t=_japanese) -> str:
    """One variable item in the words of the observation table."""
    if 'param' not in item:
        return t({'result': '戻り値', 'origin': 'エラー発生元', 'ta_crashed': 'TA の異常終了',
                  'events': '共有メモリ操作の記録', 'params': '引数全体'}.get(item['field'], item['field']))
    known = {'all': '引数 {n} 全体', 'data': '引数 {n} のデータ', 'size': '引数 {n} の長さ',
             'a': '引数 {n} の値 a', 'b': '引数 {n} の値 b'}
    return t(known.get(item['field'], '引数 {n} の {field}'), n=item['param'], field=item['field'])


def _comparison_rows(test: dict, t=_japanese) -> list[dict]:
    """Per step: what was left out of the comparison, what was compared, and whether it differed."""
    try:
        observed, repeated = test['observed'], test.get('repeated_observed')
        normal, defective = observed['normal'], observed['defective']
        variable, view = comparison(*([(observed[v], repeated[v]) for v in ('normal', 'defective')] if repeated else []))
        if not repeated:
            variable = [[] for _ in normal]
        compared_normal, compared_defective = view(normal), view(defective)
        return [{'step': step, 'normal': n, 'defective': d, 'different': n != d,
                 'variable': [_item_label(item, t) for item in items]}
                for step, n, d, items in zip(test['steps'], compared_normal, compared_defective, variable)]
    except (KeyError, TypeError, IndexError, AttributeError):
        return []


def _as(value, kind):
    """Damaged records are still listed, so every level is read defensively."""
    return value if isinstance(value, kind) else kind()


def _case_summary(case_id: str, info: dict) -> dict:
    labels = _as(info.get("labels"), dict)
    normal = _as(labels.get("normal"), dict)
    defects = _as(labels.get("defects"), list)
    semantic = _as(_as(info.get("verification"), dict).get("semantic"), dict)
    machine = _as(semantic.get("machine_validation"), dict)
    classes = Counter(str(d.get("class", UNKNOWN)) for d in defects if isinstance(d, dict))
    return {"id": case_id, "info": info, "normal": normal.get("path", UNKNOWN),
            "classes": dict(classes), "machine": machine.get("status", UNKNOWN)}


def _submitted_checks(data, defects: list, is_json: bool) -> dict:
    """The three confirmations per defect, from a JSON body or an HTML form."""
    if not is_json:
        return {d["id"]: {key: data.get(f"{d['id']}.{key}") == "on" for key in CHECKS} for d in defects}
    checks = data.get("checks", {})
    if not isinstance(checks, dict):
        abort(400, "Invalid checks")
    if set(checks) - {d["id"] for d in defects}:
        abort(400, "Unknown defect")
    for value in checks.values():
        if not isinstance(value, dict) or set(value) - set(CHECKS) or any(type(v) is not bool for v in value.values()):
            abort(400, "Checks must be booleans")
    return {d["id"]: {key: checks.get(d["id"], {}).get(key, False) for key in CHECKS} for d in defects}


def _form_target(data, prefix, role):
    path, function, start, end = (data.get(f"{prefix}.{key}", "").strip()
                                  for key in ("path", "function", "start", "end"))
    if any((path, function, start, end)):
        return {"path": path, "function": function, "role": role, "lines": [int(start), int(end or start)]}


def _submitted_targets(data, defect, source, is_json):
    """The complete corrected locations of one defect. A form may omit a role to keep it."""
    did, current = defect["id"], defect["detector_targets"]
    by_role = {t["role"]: t for t in current}
    if is_json:
        proposed = data["targets"]
    else:
        proposed = []
        for role in TARGET_ROLES:
            prefix = f"{did}.{role}"
            target = _form_target(data, prefix, role) if prefix + ".path" in data else by_role.get(role)
            if target is not None:
                proposed.append(target)
    validate_target_roles(proposed)
    for target in proposed:
        validate_target(target, source)
    updated = {target["role"]: target for target in proposed}
    return current if updated == by_role else [updated[role] for role in TARGET_ROLES if role in updated]


@contextmanager
def _write_lock(work_dir: Path, thread_lock):
    with thread_lock:
        work_dir.mkdir(parents=True, exist_ok=True)
        with (work_dir / ".review.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def create_app(benchmark_dir: Path, classes: dict, work_dir: Path, required_reviewers: int = 1,
               descriptions_ja: dict | None = None, lan: bool = False) -> Flask:
    """descriptions_ja: class name -> Japanese definition, shown when the screen is in Japanese.

    lan: also answer clients on the local network, not only this machine. Nothing authenticates them.
    """
    if type(required_reviewers) is not int or required_reviewers < 1:
        raise ValueError("required_reviewers must be a positive integer")
    benchmark_dir, work_dir = Path(benchmark_dir).resolve(), Path(work_dir).resolve()
    app = Flask(__name__)
    app.config.update(CSRF_TOKEN=secrets.token_urlsafe(32), MAX_CONTENT_LENGTH=1024 * 1024)
    lock = threading.RLock()

    @app.before_request
    def protect_local_server():
        host = urlsplit("http://" + request.host).hostname
        # A shared site is opened by address only: DNS rebinding can point any name at this server.
        host_ok = host in LOCAL_HOSTS or (lan and _address(host) is not None)
        client_ok = request.remote_addr in LOCAL_ADDRESSES or (lan and _on_lan(request.remote_addr))
        if not (host_ok and client_ok):
            abort(403, "This review server is for the local network only, opened by IP address." if lan
                  else "This review server is localhost only.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                abort(403, "Origin mismatch")
            body = request.get_json(silent=True) if request.is_json else request.form
            token = request.headers.get("X-CSRF-Token") or (body.get("csrf_token", "") if hasattr(body, "get") else "")
            if not isinstance(token, str) or not secrets.compare_digest(token, app.config["CSRF_TOKEN"]):
                abort(403, "Invalid CSRF token")

    def language():
        """?lang= wins and is remembered in a cookie; Japanese is the default."""
        chosen = request.args.get('lang') or request.cookies.get('lang')
        return chosen if chosen in LANGUAGES else 'ja'

    def t(text, **values):
        return translate(language(), text, **values)

    def definition(name):
        value = classes.get(name, {})
        english = value.get('description', value.get('definition')) if isinstance(value, dict) else value
        return (descriptions_ja or {}).get(name, english) if language() == 'ja' else english

    @app.context_processor
    def wording():
        other = 'ja' if language() == 'en' else 'en'
        arguments = {**request.args.to_dict(), 'lang': other}
        return {'lang': language(), 't': t, 'definition': definition,
                'status_labels': STATUS_LABELS[language()],
                'audience': 'LAN' if lan else 'LOCALHOST',
                'language_url': request.path + '?' + urlencode(arguments),
                'comparison_rows': lambda test: _comparison_rows(test, t)}

    @app.after_request
    def security_headers(response):
        if request.args.get('lang') in LANGUAGES:
            response.set_cookie('lang', request.args['lang'], samesite='Strict', httponly=True)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def locate(case_id):
        if not CASE_ID.fullmatch(case_id):
            abort(404)
        case_dir = benchmark_dir / "defective" / case_id
        if not case_dir.is_dir() or case_dir.is_symlink():
            abort(404)
        return case_dir

    @app.get("/")
    def index():
        with lock:  # not during a save in another thread: its temporary file would read as damage
            cases = [_case_summary(path.name, inspect_case(path, benchmark_dir, classes))
                     for path in case_paths(benchmark_dir)]
        return render_template("index.html", cases=cases, required_reviewers=required_reviewers)

    @app.get("/cases/<case_id>")
    def detail(case_id):
        case_dir = locate(case_id)
        with lock:
            info = inspect_case(case_dir, benchmark_dir, classes)
        labels = info.get("labels") or {}
        if blocking_warnings(info):
            return render_template("invalid.html", case_id=case_id, info=info)
        reviewer = request.args.get("reviewer", "")[:200]
        own_checks = {}
        for did, version in info["defect_versions"].items():
            votes = latest_reviews(labels, did, info["hashes"], version)
            own_checks[did] = votes.get(reviewer, {}).get("checks", {}).get(did, {})
        try:
            sources = compare_sources(Path(info["normal_dir"]), case_dir / "source")
            diff_path = case_dir / "changes.diff"
            diff = "" if diff_path.is_symlink() else diff_path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            sources, diff = {}, ""
        return render_template("case.html", case_id=case_id, info=info, labels=labels, classes=classes,
                               sources=sources, diff=diff, reviewer=reviewer, own_checks=own_checks,
                               csrf_token=app.config["CSRF_TOKEN"], required_reviewers=required_reviewers,
                               reviewable=reviewable(info), check_keys=CHECKS, annotations=source_annotations(labels),
                               expected_against=canonical_hash(info["hashes"]))

    @app.post("/cases/<case_id>/review", defaults={"defect_id": None})
    @app.post("/cases/<case_id>/defects/<defect_id>/review")
    def save_review(case_id, defect_id):
        case_dir = locate(case_id)
        data = request.get_json(silent=True) if request.is_json else request.form
        if not isinstance(data, dict) and not hasattr(data, "get"):
            abort(400, "Invalid review")
        reviewer = data.get("reviewer", "")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
            abort(400, t("評価者名を入力してください。"))
        reviewer = reviewer.strip()
        action = data.get("action", "save")
        if not isinstance(action, str) or action not in ACTIONS or (action == "edit" and not defect_id):
            abort(400, "Unknown action")
        reason = data.get(f"{defect_id}.reason", data.get("reason", ""))
        if not isinstance(reason, str) or len(reason) > 10000:
            abort(400, "Invalid reason")
        if action == "reject" and not reason.strip():
            abort(400, t("却下理由を入力してください。"))
        with _write_lock(benchmark_dir, lock):
            info = inspect_case(case_dir, benchmark_dir, classes)
            if not reviewable(info):
                abort(409, t("整合性または機械検証を確認してください。現在のケースはレビューを保存できません。"))
            labels = info["labels"]
            defects = labels["defects"]
            if defect_id:
                defects = [d for d in defects if d["id"] == defect_id]
                if not defects:
                    abort(404)
            expected = data.get(f"{defect_id}.expected", data.get("expected_against"))
            version = info["defect_versions"][defect_id] if defect_id else canonical_hash(info["hashes"])
            if expected != version:
                abort(409, t("表示後にケースが変更されました。再読み込みして確認し直してください。"))
            checks = _submitted_checks(data, defects, request.is_json)
            if action == "approve" and not all(all(row.values()) for row in checks.values()):
                abort(400, t("承認する不備の分類・位置・挙動を確認してください。"))
            targets = None
            fields = ("targets",) if request.is_json else (
                f"{defect_id}.effect.path", f"{defect_id}.protection.path")
            has_target = any(field in data for field in fields)
            if not defect_id and has_target:
                abort(400, "A label correction must select one defect")
            if defect_id and (action == "edit" or (has_target and action in {"save", "approve"})):
                try:
                    proposed = _submitted_targets(data, defects[0], case_dir / "source", request.is_json)
                except (KeyError, ValueError) as exc:
                    abort(400, t("正解位置を保存できません。ファイル・関数・行範囲を確認してください。") + f" ({exc})")
                if proposed != defects[0]["detector_targets"]:
                    targets = proposed
            if action == "edit":
                checks = {defect_id: dict.fromkeys(CHECKS, False)}
            status, states = info["status"], info["defect_statuses"]
            if action != "edit" or targets is not None:
                change = record_decision(info, defects, reviewer, action, checks, reason.strip(), targets, required_reviewers)
                publish_review(case_dir, labels, info["label_history"], change)
                review = labels["review"]
                status, states = review["status"], {did: state["status"] for did, state in review["per_defect"].items()}
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return {"status": status, "per_defect": states, "reviewer": reviewer}
        return redirect(url_for("detail", case_id=case_id, reviewer=reviewer,
                                _anchor=("defect-" + defect_id) if defect_id else "review"), code=303)

    return app
