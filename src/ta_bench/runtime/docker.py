"""Offline, resource-bounded OP-TEE/QEMU execution. No native fallback."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import uuid as uuidlib
from pathlib import Path
from typing import Any

from ..common.jsonio import atomic_json, canonical_hash, load_json
from ..common.sources import source_digest
from ..errors import ExecutionError, ValidationError
from .events import INSTRUMENTATION, instrument_source, required_features
from .observations import validate_observations


class DockerRunner:
    def __init__(self, image: str, work_dir: Path, timeout: int = 300,
                 memory: str = '4g', cpus: float = 2, development: bool = False):
        if timeout <= 0 or cpus <= 0:
            raise ExecutionError('Timeout and CPU limit must be positive')
        if not re.fullmatch(r'[1-9][0-9]*[kKmMgG]?', memory):
            raise ExecutionError('Invalid Docker memory limit')
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.timeout, self.memory, self.cpus = timeout, memory, cpus
        pinned = bool(re.fullmatch(r'(?:[^\s]+@)?sha256:[a-f0-9]{64}', image))
        if not pinned and not development:
            raise ExecutionError('Use an immutable image digest (repository@sha256:... or sha256:...), or --development')
        try:
            proc = subprocess.run(['docker', 'image', 'inspect', image], check=True,
                                  capture_output=True, text=True, timeout=30)
            info = json.loads(proc.stdout)[0]
        except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
            raise ExecutionError('Cannot inspect runtime image; build or pull docker/Dockerfile first') from exc
        labels = info.get('Config', {}).get('Labels') or {}
        keys = ('optee_revision', 'qemu_revision', 'toolchain', 'runner_version')
        missing = [key for key in keys if not labels.get('org.ta-bench.' + key)]
        if missing:
            raise ExecutionError('Image lacks runtime metadata: ' + ', '.join(missing))
        self.image = info['Id']  # Freeze even development tags before any execution.
        digest = image.split('@')[-1] if pinned else self.image
        self.environment = {key: labels['org.ta-bench.' + key] for key in keys}
        self.environment['image_digest'] = digest
        self.environment['platform'] = info.get('Os', '') + '/' + info.get('Architecture', '')
        self.features = frozenset(labels.get('org.ta-bench.features', '').split())
        self.publishable = (pinned and not development and platform.system() == 'Linux'
                            and platform.machine() in ('x86_64', 'amd64')
                            and self.environment['platform'] == 'linux/amd64')
        if not development and not self.publishable:
            raise ExecutionError('Benchmark publication requires Linux amd64; use --development elsewhere')

    def _command(self, name: str, input_dir: Path, output_dir: Path, mode: str) -> list[str]:
        # Only per-operation inputs/outputs are mounted; never credentials, HOME or socket.
        for path in (input_dir, output_dir):
            if ',' in str(path):
                raise ExecutionError('Docker mount paths may not contain commas')
        return ['docker', 'run', '--rm', '--name', name, '--network', 'none',
                '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--user', f'{os.getuid()}:{os.getgid()}', '--pids-limit', '256',
                '--memory', self.memory, '--memory-swap', self.memory,
                '--cpus', str(self.cpus), '--ulimit', 'fsize=536870912:536870912',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=2g',
                '--mount', f'type=bind,src={input_dir},dst=/input,readonly',
                '--mount', f'type=bind,src={output_dir},dst=/output',
                self.image, mode]

    def _execute(self, input_dir: Path, output_dir: Path, mode: str) -> None:
        name = 'ta-bench-' + uuidlib.uuid4().hex
        output_dir.mkdir(parents=True, exist_ok=True)
        log = output_dir / 'container.log'
        try:
            with log.open('wb') as stream:
                subprocess.run(self._command(name, input_dir, output_dir, mode),
                               stdout=stream, stderr=subprocess.STDOUT, check=True,
                               timeout=self.timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ExecutionError(f'{mode} failed; see {log}') from exc
        finally:
            # subprocess timeout alone only kills Docker's client, not its container.
            try:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15, check=False)
            except (OSError, subprocess.SubprocessError):
                pass

    def build(self, source: Path, checkpoints=None) -> Path:
        source = Path(source).resolve()
        identity = {'source': source_digest(source), 'image': self.image}
        if checkpoints:
            identity['instrumentation'] = {'method': INSTRUMENTATION, 'checkpoints': checkpoints}
        key = canonical_hash(identity).split(':')[1]
        output = self.work_dir / 'builds' / key
        manifest = output / 'artifact.json'
        if manifest.exists():
            try:
                data = load_json(manifest)
                artifact = output / 'ta'
                if (isinstance(data, dict) and list(artifact.glob('*.ta'))
                        and data.get('digest') == source_digest(artifact)):
                    return artifact
            except (OSError, ValidationError):
                # Interrupted or damaged caches are not evidence. Rebuild into
                # a new directory while preserving the old files for diagnosis.
                pass
        # Cache is finalized only after a successful build; failed dirs remain logs.
        attempt = self.work_dir / 'builds' / (key + '-' + uuidlib.uuid4().hex[:8])
        build_source = source
        if checkpoints:
            attempt.mkdir(parents=True)
            build_source = attempt / 'instrumented-source'
            evidence = instrument_source(source, build_source, checkpoints)
            atomic_json(attempt / 'instrumentation.json', evidence)
        self._execute(build_source, attempt, 'build')
        files = list(attempt.glob('*.ta'))
        if not files or any(p.is_symlink() for p in files):
            raise ExecutionError(f'Build produced no regular .ta artifacts: {attempt}')
        ta_dir = attempt / 'ta'
        ta_dir.mkdir()
        for path in files:
            shutil.copyfile(path, ta_dir / path.name)
        atomic_json(attempt / 'artifact.json', {'digest': source_digest(ta_dir)})
        if output.exists():
            # Another completed operation may already own this key; never replace it.
            return ta_dir
        attempt.rename(output)
        return output / 'ta'

    def run(self, build_artifact: Path, steps: list[dict[str, Any]], uuid: str) -> list[dict[str, Any]]:
        missing = required_features(steps) - self.features
        if missing:
            raise ExecutionError('runtime image lacks features: ' + ', '.join(sorted(missing)))
        run_dir = self.work_dir / 'executions' / uuidlib.uuid4().hex
        input_dir, output_dir = run_dir / 'input', run_dir / 'output'
        input_dir.mkdir(parents=True)
        for source in Path(build_artifact).glob('*.ta'):
            if source.is_symlink():
                raise ExecutionError('Symlink in TA build artifact')
            shutil.copyfile(source, input_dir / source.name)
        if not list(input_dir.glob('*.ta')):
            raise ExecutionError('Missing TA build artifact')
        atomic_json(input_dir / 'plan.json', {'uuid': str(uuidlib.UUID(uuid)), 'steps': steps})
        self._execute(input_dir, output_dir, 'run')
        try:
            observations = json.loads((output_dir / 'observations.json').read_text())
        except (OSError, ValueError) as exc:
            raise ExecutionError(f'Missing/malformed observations: {output_dir}') from exc
        return validate_observations(steps, observations)
