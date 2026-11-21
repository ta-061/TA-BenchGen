"""Re-run the frozen input plans of stored cases (review --reverify)."""
import uuid
from pathlib import Path

from ..candidate.plan import validate_plan
from ..common.jsonio import atomic_json
from ..common.locking import lock_file, now
from ..dataset.layout import blocking_warnings
from ..dataset.schema import PLAN_FIELDS
from ..dataset.store import inspect_case
from ..errors import ExecutionError, JudgmentError
from ..runtime.ta_uuid import discover_uuid
from .judge import verify


def reverify_cases(benchmark, classes, work_dir, runner):
    """Re-run frozen plans; preserve approvals iff semantic hashes are unchanged."""
    results = []
    for case in sorted((benchmark / 'defective').glob('case_*')):
        inspected = inspect_case(case, benchmark, classes)
        if not inspected['structural_valid'] or blocking_warnings(inspected):
            results.append({'case_id': case.name, 'status': 'skipped', 'reason': inspected['warnings']})
            continue
        labels, old = inspected['labels'], inspected['verification']
        normal = Path(inspected['normal_dir'])
        tests = [{k: t[k] for k in PLAN_FIELDS if k in t}
                 for t in old['semantic']['tests']]
        validate_plan(tests, labels['defects'])
        directory = work_dir / 'reverify' / case.name / uuid.uuid4().hex
        directory.mkdir(parents=True)
        atomic_json(directory / 'previous-verification.json', old)
        try:
            semantic = verify(normal, case / 'source', labels['defects'], tests, classes,
                              runner, discover_uuid(normal), directory)
        except JudgmentError as exc:
            semantic = exc.semantic
        except ExecutionError as exc:
            # Execution infrastructure errors do not replace prior measured semantic evidence.
            atomic_json(directory / 'error.json', {'status': 'execution_error', 'reason': str(exc)})
            results.append({'case_id': case.name, 'status': 'execution_error', 'reason': str(exc)})
            continue
        updated = {**old, 'semantic': semantic, 'environment': runner.environment,
                   'run_meta': {'verified_at': now(), 'run_id': 'reverify_' + directory.name}}
        if not runner.publishable:
            atomic_json(directory / 'development-verification.json', updated)
            results.append({'case_id': case.name, 'status': 'development_only'})
            continue
        with lock_file(benchmark / '.review.lock'):
            current = inspect_case(case, benchmark, classes)
            if current.get('hashes') != inspected.get('hashes'):
                results.append({'case_id': case.name, 'status': 'skipped', 'reason': 'artifacts changed during reverify'})
                continue
            atomic_json(case / 'verification.json', updated)
        results.append({'case_id': case.name, 'status': semantic['machine_validation']['status']})
    return results
