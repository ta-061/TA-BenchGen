"""Bounded candidate generation; only measured, completely validated cases are published."""
import re
import uuid
from pathlib import Path

from ..candidate.diff import compute_diff
from ..common.jsonio import atomic_json, canonical_hash, load_json
from ..common.locking import lock_file, now
from ..common.sources import source_digest
from ..dataset.schema import SCHEMA_VERSION
from ..dataset.store import inspect_case, save_case
from ..errors import ExecutionError, GenerationAPIError, JudgmentError, ValidationError
from ..runtime.observations import stable_view, variable_items
from .corpus import corpus_path, extend_corpus, load_corpus, normal_steps
from .pipeline import process_candidate, static_check
from .requests import STOPPED

RUN_ID = re.compile(r'run_[a-f0-9]{16}')
FEEDBACK_ROWS, FEEDBACK_TEXT, FEEDBACK_HEX = 12, 300, 64
FEEDBACK_CHANGES, FEEDBACK_CHANGE = 16, 1000  # source changes returned on retry, and each text's size
FEEDBACK_FIELDS = ('status', 'reason', 'proposed', 'changes', 'failed_test', 'observed_differences')
EXISTING_CASES, EXISTING_DIFF_CHARS = 30, 4000  # saved cases shown to the model, and each diff's size


def _short(value, limit):
    """An untrusted value, bounded for the run state and the next prompt."""
    if isinstance(value, str):
        return value[:limit]
    return value if value is None or type(value) is int else str(value)[:limit]


def proposed_defects(candidate):
    """What the model proposed, kept short, so a retry can correct it instead of repeating it."""
    defects = candidate.get('defects') if isinstance(candidate, dict) else None
    if not isinstance(defects, list):
        return []
    proposed = []
    for d in defects[:8]:
        if not isinstance(d, dict):
            continue
        targets = d.get('detector_targets')
        proposed.append({
            'id': _short(d.get('id'), 40), 'class': _short(d.get('class'), 40),
            'reason': _short(d.get('reason'), FEEDBACK_TEXT),
            'detector_targets': [
                {'role': _short(t.get('role'), 40), 'path': _short(t.get('path'), FEEDBACK_TEXT),
                 'function': _short(t.get('function'), FEEDBACK_TEXT),
                 'lines': [_short(n, 40) for n in t['lines'][:2]] if isinstance(t.get('lines'), list) else None}
                for t in (targets if isinstance(targets, list) else [])[:4] if isinstance(t, dict)]})
    return proposed


def proposed_changes(candidate):
    """The source changes of the last candidate, bounded, so a retry can revise them."""
    changes = candidate.get('changes') if isinstance(candidate, dict) else None
    if not isinstance(changes, list):
        return []
    return [{key: _short(c.get(key), FEEDBACK_CHANGE) for key in ('path', 'defect', 'old', 'new')}
            for c in changes[:FEEDBACK_CHANGES] if isinstance(c, dict)]


def retry_feedback(entry):
    """The part of a failed attempt that the next prompt receives; bookkeeping stays in the run state."""
    return {key: entry[key] for key in FEEDBACK_FIELDS if key in entry}


def existing_diffs(benchmark, normal_digest):
    """Diffs of the cases already saved for this normal TA, so a model can avoid repeating them."""
    diffs = []
    for case in sorted((Path(benchmark) / 'defective').glob('case_*')):
        try:
            if load_json(case / 'labels.json')['normal']['source_digest'] == normal_digest:
                diffs.append((case / 'changes.diff').read_text(encoding='utf-8')[:EXISTING_DIFF_CHARS])
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return diffs[-EXISTING_CASES:]


def _bounded_bytes(value):
    """Keep sequence structure and lengths; mark shortened hex buffers explicitly."""
    if isinstance(value, list):
        return [_bounded_bytes(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _bounded_bytes(item) for key, item in value.items()}
    for key in ('data', 'before', 'after'):
        data = value.get(key)
        if isinstance(data, str) and len(data) > FEEDBACK_HEX:
            result[key] = data[:FEEDBACK_HEX]
            result[key + '_bytes'] = len(data) // 2
            result[key + '_truncated'] = True
    return result


def _brief(row, ignored=()):
    compared = stable_view(row, ignored)
    outputs = [{'param': index, **p} for index, p in enumerate(compared.get('params', []))
               if isinstance(p, dict) and str(p.get('type', '')).endswith(('_output', '_inout'))]
    # Raw status remains visible even if it varied: R2 checks crashes before comparing fields.
    return _bounded_bytes({'result': row.get('result'), 'origin': row.get('origin'),
                           'ta_crashed': row.get('ta_crashed'), 'outputs': outputs})


def _feedback_row(test, step):
    ignored = next((item['items'] for item in test.get('variable_items', []) if item['step'] == step), [])
    normal, defective = (test['observed'][variant][step - 1] for variant in ('normal', 'defective'))
    row = {'test': test['id'], 'purpose': test['purpose'], 'step': step,
           'normal': _brief(normal, ignored), 'defective': _brief(defective, ignored),
           'ignored_variable_items': ignored,
           'different_items': variable_items(stable_view(normal, ignored), stable_view(defective, ignored))}
    for variant, observations in test.get('repeated_observed', {}).items():
        row['repeated_' + variant] = _brief(observations[step - 1], ignored)
    return row


def observed_differences(semantic):
    """Measured normal/defective rows that differed, bounded for retry feedback."""
    rows = []
    for test in semantic.get('tests', []):
        for step in test.get('different_steps', []):
            rows.append(_feedback_row(test, step))
    return rows[:FEEDBACK_ROWS]


def failed_test_feedback(semantic, candidate_tests):
    """Explain the test named by the judge, including equal errors and earlier setup steps."""
    reason = semantic.get('machine_validation', {}).get('reason', '')
    for test in semantic.get('tests', []):
        if not reason.startswith(test['id'] + ': '):
            continue
        # Keep the first crash/error in each execution and the witness even in long sequences.
        priority = []
        for executions in ('observed', 'repeated_observed'):
            for rows in test.get(executions, {}).values():
                for field in ('ta_crashed', 'result'):
                    first_error = next((i for i, row in enumerate(rows, 1) if row[field]), None)
                    if first_error is not None:
                        priority.append(first_error)
        if 'witness_step' in test:
            priority.append(test['witness_step'])
        priority.extend(test.get('different_steps', []))
        priority.extend(range(1, len(test['steps']) + 1))
        selected = sorted(list(dict.fromkeys(priority))[:FEEDBACK_ROWS])
        return {'id': test['id'], 'purpose': test['purpose'],
                'source': 'candidate' if test['id'] in {t['id'] for t in candidate_tests} else 'corpus',
                'steps': _bounded_bytes(test['steps']),
                'observations': [_feedback_row(test, step) for step in selected],
                'observations_omitted': len(test['steps']) - len(selected)}
    return None


def run_generation(requests_spec, classes, benchmark, work_dir, provider_factory, runner_factory,
                   resume=None, progress=print, settings=None):
    """Run (or resume) every request and return the requested/saved/unmet summary."""
    benchmark, work_dir = Path(benchmark).resolve(), Path(work_dir).resolve()
    if resume and not RUN_ID.fullmatch(resume):
        raise ValidationError('invalid run ID')
    run_id = resume or 'run_' + uuid.uuid4().hex[:16]
    run_dir = work_dir / 'runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with lock_file(run_dir / '.lock'):
        session = _Session(run_id, run_dir, classes, benchmark, work_dir,
                           provider_factory, runner_factory, progress)
        if resume:
            session.load_state()
            if settings is not None:
                # The CLI restores initial settings and can add a resolved model
                # profile when resuming a run created before profiles were frozen.
                session.state['settings'] = settings
            session.recover_publications()
        else:
            session.new_state(requests_spec, settings)
        session.save_state()
        progress(f'run_id: {run_id}')
        for index, req in enumerate(session.state['requests']):
            if session.run_request(index, req):
                break
        session.state['updated_at'] = now()
        session.save_state()
        requests = session.state['requests']
        return {'run_id': run_id, 'requested': sum(r['count'] for r in requests),
                'saved': sum(len(r['saved']) for r in requests),
                'unmet': sum(r['count'] - len(r['saved']) for r in requests),
                'provider_declined': sum('provider_declined' in r for r in requests),
                'exhausted': sum('exhausted' in r for r in requests), 'requests': requests}


class _Session:
    """State of one run. The provider and runner are created on first use."""

    def __init__(self, run_id, run_dir, classes, benchmark, work_dir,
                 provider_factory, runner_factory, progress):
        self.run_id, self.run_dir = run_id, run_dir
        self.classes, self.benchmark, self.work_dir = classes, benchmark, work_dir
        self.provider_factory, self.runner_factory = provider_factory, runner_factory
        self.progress = progress
        self.state_file = run_dir / 'state.json'
        self.state = None
        self.provider = self.runner = None

    # ---- state ---------------------------------------------------------

    def save_state(self):
        atomic_json(self.state_file, self.state)

    def new_state(self, requests_spec, settings):
        self.state = {'run_id': self.run_id, 'created_at': now(), 'benchmark': str(self.benchmark),
                      'classes_digest': canonical_hash(self.classes), 'requests': [],
                      'settings': settings or {}}
        for req in requests_spec:
            # Validate the supplied root before resolve() can hide a symlink.
            normal_digest = source_digest(Path(req['ta']))
            normal = Path(req['ta']).resolve()
            self.state['requests'].append({**req, 'ta': str(normal), 'normal_digest': normal_digest,
                                           'saved': [], 'attempts': []})

    def load_state(self):
        self.state = load_json(self.state_file)
        if (self.state['benchmark'] != str(self.benchmark)
                or self.state['classes_digest'] != canonical_hash(self.classes)):
            raise ValidationError('resume requires the same benchmark directory and class definitions')

    def recover_publications(self):
        """A directory rename may have succeeded just before the process died.

        Recover publications from their provenance instead of generating duplicates.
        """
        requests = self.state['requests']
        for case in sorted((self.benchmark / 'defective').glob('case_*')):
            info = inspect_case(case, self.benchmark, self.classes)
            if not info['structural_valid'] or info['warnings']:
                continue
            record = info['verification']
            if record['semantic']['machine_validation']['status'] != 'machine_pass':
                continue
            meta = record['run_meta']
            if meta.get('run_id') != self.run_id:
                continue
            idx = meta.get('request_index', 0) - 1
            if not 0 <= idx < len(requests):
                continue
            req = requests[idx]
            if case.name not in req['saved']:
                req['saved'].append(case.name)
            attempt = record['generation']['attempt_index']
            if 1 <= attempt <= len(req['attempts']):
                req['attempts'][attempt - 1].update(status='machine_pass', reason='recovered publication',
                                                    case_id=case.name)
            extend_corpus(self.work_dir, corpus_path(self.work_dir, req['normal_digest']),
                          normal_steps(record['semantic']['tests']))

    # ---- requests and attempts -----------------------------------------

    def run_request(self, index, req) -> bool:
        """Attempt one request until it is met or exhausted. True stops the whole run."""
        normal = Path(req['ta'])
        if source_digest(normal) != req['normal_digest']:
            raise ValidationError('normal TA changed since this run started; start a new run')
        unsupported = [name for name in req['defects'] if not self.classes[name]['supported']]
        if unsupported:
            req['unsupported'] = {name: self.classes[name].get('unsupported_reason', 'unsupported')
                                  for name in unsupported}
            self.save_state()
            return False
        if STOPPED & set(req):
            return False
        while len(req['saved']) < req['count'] and len(req['attempts']) < req['max_attempts']:
            stop = self.attempt(index, req, normal)
            if STOPPED & set(req) or stop:
                return stop
        return False

    def attempt(self, index, req, normal) -> bool:
        """One candidate. Every outcome is recorded; True means retrying cannot help."""
        number = len(req['attempts']) + 1
        attempt_dir = self.run_dir / f'request_{index + 1}' / f'attempt_{number}'
        attempt_dir.mkdir(parents=True, exist_ok=True)
        entry = {'index': number, 'status': 'interrupted', 'reason': 'attempt did not finish'}
        req['attempts'].append(entry)
        self.save_state()
        self.progress(f'request {index + 1}: attempt {number}/{req["max_attempts"]}')
        stop = False
        try:
            self._generate_and_publish(index, req, normal, number, attempt_dir, entry)
        except JudgmentError as exc:
            entry.update(status=exc.status, reason=str(exc))
            if exc.semantic:
                atomic_json(attempt_dir / 'failed-semantic.json', exc.semantic)
                differences = observed_differences(exc.semantic)
                if differences:
                    entry['observed_differences'] = differences
                failed_test = failed_test_feedback(exc.semantic, load_json(attempt_dir / 'candidate.json')['tests'])
                if failed_test:
                    entry['failed_test'] = failed_test
            if exc.status == 'unsupported' and 'exhausted' not in req:
                req['unsupported'] = str(exc)
        except ValidationError as exc:
            entry.update(status='machine_fail', reason=str(exc))
        except GenerationAPIError as exc:
            entry.update(status='execution_error', reason=str(exc), retryable=exc.retryable)
            if exc.declined:
                # A filter or refusal is a result for this request, never retried; later
                # requests are independent conversations and still run.
                entry['provider_declined'] = True
                req['provider_declined'] = str(exc)
            else:
                stop = not exc.retryable
        except (ExecutionError, OSError) as exc:
            entry.update(status='execution_error', reason=str(exc))
        atomic_json(attempt_dir / 'result.json', entry)
        self.save_state()
        self.progress(f'  {entry["status"]}: {entry["reason"]}')
        return stop

    def _generate_and_publish(self, index, req, normal, number, attempt_dir, entry):
        if self.runner is None:
            self.runner = self.runner_factory()
        required = {feature for name in req['defects']
                    for feature in self.classes[name].get('required_features', [])}
        missing = required - set(getattr(self.runner, 'features', ()))
        if missing:
            raise JudgmentError('unsupported', 'runtime image lacks features: ' + ', '.join(sorted(missing)))
        if self.provider is None:
            self.provider = self.provider_factory()
        feedback = retry_feedback(req['attempts'][-2]) if number > 1 else None
        existing = existing_diffs(self.benchmark, req['normal_digest'])
        candidate = self.provider.propose(normal, req['defects'], self.classes, feedback, attempt_dir,
                                          existing=existing)
        atomic_json(attempt_dir / 'candidate.json', candidate)
        proposed = proposed_defects(candidate)
        if proposed:
            entry['proposed'] = proposed
        changes = proposed_changes(candidate)
        if changes:
            entry['changes'] = changes
        if isinstance(candidate, dict) and set(candidate) == {'exhausted'}:
            # The model's own statement, and only meaningful against cases it was shown.
            if not existing:
                raise ValidationError('exhausted needs saved cases in existing; answer unsupported '
                                      'if no code fits the class')
            req['exhausted'] = str(candidate['exhausted'])
            raise JudgmentError('unsupported', 'no further distinct defect: ' + req['exhausted'])
        if isinstance(candidate, dict) and 'unsupported' in candidate:
            raise JudgmentError('unsupported', str(candidate['unsupported']))

        inputs = corpus_path(self.work_dir, req['normal_digest'])
        source, defects, tests, plan_digest, semantic = process_candidate(
            candidate, normal, req['defects'], self.classes, self.benchmark, attempt_dir,
            self.runner, load_corpus(inputs))
        if source_digest(normal) != req['normal_digest']:
            raise ValidationError('normal TA changed during verification')

        case_id = 'case_' + uuid.uuid4().hex[:16]
        labels = self._labels(case_id, normal, req, defects)
        verification = self._verification(case_id, number, plan_digest, semantic, index)
        atomic_json(attempt_dir / 'verification.json', verification)
        if not self.runner.publishable:
            raise JudgmentError('unsupported', 'development environment: benchmark publication disabled', semantic)

        # Serialize duplicate check and atomic publication across generation runs.
        defective = self.benchmark / 'defective'
        with lock_file(self.benchmark / '.dataset.lock'):
            static_check(normal, source, defects, self.classes, defective)
            saved = save_case(defective, source, labels, verification, compute_diff(normal, source))
            req['saved'].append(saved.name)
            entry.update(status='machine_pass', reason='saved', case_id=saved.name)
            self.save_state()
        extend_corpus(self.work_dir, inputs, normal_steps(tests))

    # ---- records ---------------------------------------------------------

    def _labels(self, case_id, normal, req, defects):
        try:
            normal_ref = normal.relative_to(self.benchmark).as_posix()
        except ValueError:
            normal_ref = str(normal)
        return {'schema_version': SCHEMA_VERSION, 'case_id': case_id,
                'normal': {'path': normal_ref, 'source_digest': req['normal_digest']},
                'defects': defects,
                'review': {'status': 'unreviewed', 'reviews': [], 'approved_against': None}}

    def _verification(self, case_id, number, plan_digest, semantic, index):
        return {'schema_version': SCHEMA_VERSION, 'case_id': case_id,
                'environment': self.runner.environment,
                'generation': {'model_id': self.provider.model_id, 'attempt_index': number,
                               'attempts_total': number, 'plan_digest': plan_digest},
                'semantic': semantic,
                'run_meta': {'verified_at': now(), 'run_id': self.run_id, 'request_index': index + 1}}
