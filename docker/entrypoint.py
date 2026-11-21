"""Trusted image-side adapter. Inputs are data; each run boots a new RAM rootfs."""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, '/opt/ta-bench/python')
from ta_bench.candidate.plan import kept_outputs, validate_steps
from ta_bench.runtime.events import checkpoint_id

INPUT, OUTPUT = Path('/input'), Path('/output')
ROOT = Path('/opt/optee')
TRUSTED = Path('/opt/ta-bench')


def build() -> None:
    tree = Path('/tmp/source')
    shutil.copytree(INPUT, tree, symlinks=False)
    # Keep __DATE__, __TIME__, __TIMESTAMP__ and source paths identical across
    # variants. Differences in host file mtimes are not experimental inputs.
    for path in tree.rglob('*'):
        if path.is_file():
            os.utime(path, (0, 0))
    kit = ROOT / 'optee_os/out/arm/export-ta_arm64'
    compiler = next((ROOT / 'toolchains/aarch64/bin').glob('aarch64*-gcc'))
    env = dict(os.environ, HOME='/tmp', CCACHE_DISABLE='1',
               SOURCE_DATE_EPOCH='0', TZ='UTC', LC_ALL='C')
    subprocess.run(['make', '-C', str(tree / 'ta'), '-j2',
                    'TA_DEV_KIT_DIR=' + str(kit),
                    'CROSS_COMPILE=' + str(compiler)[:-3],
                    'O=/tmp/ta-build'], check=True, env=env)
    paths = list(Path('/tmp/ta-build').rglob('*.ta'))
    if not paths:
        raise RuntimeError('TA Makefile must honor O=/tmp/ta-build; stale in-tree artifacts are not accepted')
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('TA output must be a regular file')
        shutil.copyfile(path, OUTPUT / path.name)


def encode_plan(plan: dict) -> bytes:
    """Bounded line protocol consumed only by the common C client."""
    names: dict[str, int] = {}
    lines = []
    target = str(uuid.UUID(plan['uuid']))
    kinds = {'none': 0, 'value_input': 1, 'value_output': 2, 'value_inout': 3,
             'memref_input': 5, 'memref_output': 6, 'memref_inout': 7,
             'shared_memref_input': 8, 'shared_memref_output': 9, 'shared_memref_inout': 10}
    validate_steps(plan['steps'])
    if not 1 <= len(plan['steps']) <= 1024:
        raise ValueError('Input plan must contain 1..1024 steps')
    kept = kept_outputs(plan['steps'])
    for number, step in enumerate(plan['steps'], 1):
        name = step['session']
        if name not in names:
            names[name] = len(names)
        sid = names[name]
        if sid >= 32:
            raise ValueError('At most 32 sessions per plan')
        op = step['op']
        if op == 'open':
            if step.get('uuid', target) != target:
                raise ValueError('Open UUID must equal TA UUID')
            lines.append(f'O {sid} {target}')
        elif op == 'close':
            lines.append(f'C {sid}')
        elif op == 'invoke':
            cmd = step['command_id']
            if type(cmd) is not int or not 0 <= cmd <= 0xFFFFFFFF:
                raise ValueError('Invalid command ID')
            params = step['params']
            if len(params) != 4:
                raise ValueError('Invoke requires exactly four parameters')
            tokens = ['I', str(sid), str(cmd)]
            for event in step.get('events', []):
                trigger, action = event['trigger'], event['action']
                lines.append(' '.join(map(str, ['M', checkpoint_id(trigger), trigger['occurrence'],
                                               action['param'], action['offset'],
                                               action['expect'].lower(), action['data'].lower()])))
            for index in (p for s, p in kept if s == number):
                lines.append(f'K {index}')
            for index, param in enumerate(params):
                for item in param.get('inserts', []):
                    source = item['from']
                    lines.append(' '.join(map(str, ['R', index, item['offset'], source['step'],
                                                   source['param'], source['offset'], source['length']])))
            for param in params:
                kind = kinds[param['type']]
                a, b = param.get('a', 0), param.get('b', 0)
                if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in (a, b)):
                    raise ValueError('Invalid uint32 parameter')
                data = bytes.fromhex(param.get('data', ''))
                size = param.get('size', len(data))
                if type(size) is not int or not 0 <= size <= 1048576 or len(data) > size:
                    raise ValueError('Invalid memref size (limit 1 MiB)')
                tokens += [str(kind), str(a), str(b), str(size), data.hex() or '-']
            lines.append(' '.join(tokens))
        else:
            raise ValueError('Unknown input operation')
    return ('\n'.join(lines) + '\n').encode('ascii')


def cpio_overlay(files: dict[str, bytes]) -> bytes:
    """Create deterministic newc, without requiring mknod or root."""
    output = bytearray()
    directories = {'ta-bench'}
    for name in files:
        directories.update(str(p) for p in Path(name).parents if str(p) != '.')
    entries = [(name, b'', stat.S_IFDIR | 0o755) for name in sorted(directories)]
    entries += [(name, data, stat.S_IFREG | (0o755 if name.endswith(('init', 'ta-invoke')) else 0o644))
                for name, data in files.items()]
    entries.append(('TRAILER!!!', b'', 0))
    for index, (name, data, mode) in enumerate(entries):
        encoded = name.encode() + b'\0'
        fields = [index + 1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        output.extend(b'070701' + ''.join(f'{v:08x}' for v in fields).encode())
        output.extend(encoded)
        output.extend(b'\0' * (-len(output) % 4))
        output.extend(data)
        output.extend(b'\0' * (-len(output) % 4))
    output.extend(b'\0' * (-len(output) % 512))
    return bytes(output)


def run() -> None:
    plan = json.loads((INPUT / 'plan.json').read_text())
    marker = 'TA_BENCH_' + uuid.uuid4().hex
    files = {'ta-bench/plan.txt': encode_plan(plan),
             'ta-bench/ta-invoke': (TRUSTED / 'ta-invoke').read_bytes(),
             'ta-bench/plugins/events.plugin': (TRUSTED / 'events.plugin').read_bytes()}
    for path in INPUT.glob('*.ta'):
        if not re.fullmatch(r'[0-9a-fA-F-]{36}\.ta', path.name) or path.is_symlink():
            raise ValueError('Invalid TA artifact name')
        files['ta-bench/' + path.name] = path.read_bytes()
    init = '''#!/bin/sh
export PATH=/sbin:/usr/sbin:/bin:/usr/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
dmesg -n 1
mkdir -p /run /tmp /var/lib/tee /lib/optee_armtz
cp /ta-bench/*.ta /lib/optee_armtz/
tee-supplicant -d -p /ta-bench/plugins
/ta-bench/ta-invoke < /ta-bench/plan.txt > /tmp/observations
result=$?
echo MARKER_BEGIN_$result
base64 /tmp/observations
echo MARKER_END
sync
poweroff -f
'''.replace('MARKER', marker)
    files['init'] = init.encode()
    boot = Path('/tmp/boot')
    boot.mkdir()
    for path in (TRUSTED / 'boot').iterdir():
        if path.name != 'rootfs.cpio.gz':
            shutil.copyfile(path, boot / path.name)
    archive = gzip.decompress((TRUSTED / 'boot/rootfs.cpio.gz').read_bytes())
    (boot / 'rootfs.cpio.gz').write_bytes(gzip.compress(archive + cpio_overlay(files), mtime=0))
    # Upstream U-Boot loads these wrapped images through semihosting, and sets
    # its own bootargs. The overlay therefore supplies /init directly.
    subprocess.run([str(ROOT / 'u-boot/tools/mkimage'), '-A', 'arm64', '-T', 'ramdisk',
                    '-C', 'gzip', '-a', '0x45000000', '-e', '0x45000000',
                    '-n', 'TA benchmark rootfs', '-d', str(boot / 'rootfs.cpio.gz'),
                    str(boot / 'rootfs.cpio.uboot')], check=True)
    command = [(TRUSTED / 'qemu-path').read_text().strip(),
               '-machine', 'virt,acpi=off,secure=on,mte=off,gic-version=3,virtualization=false',
               '-cpu', 'max,sme=on,pauth-impdef=on', '-smp', '2', '-m', '1057',
               '-accel', 'tcg', '-display', 'none', '-monitor', 'none', '-nic', 'none',
               '-object', 'rng-random,filename=/dev/urandom,id=rng0',
               '-device', 'virtio-rng-pci,rng=rng0,max-bytes=1024,period=1000',
               '-no-reboot', '-bios', 'bl1.bin', '-kernel', 'Image',
               '-initrd', 'rootfs.cpio.gz',
               '-append', 'console=ttyAMA0,38400 keep_bootcon rdinit=/init',
               '-serial', 'file:/output/serial-normal.log',
               '-serial', 'file:/output/serial-secure.log',
               '-semihosting-config', 'enable=on,target=native']
    # The outer DockerRunner enforces the deadline and removes the container.
    subprocess.run(command, cwd=boot, check=True)
    serial = (OUTPUT / 'serial-normal.log').read_text(errors='replace')
    match = re.search(re.escape(marker) + r'_BEGIN_(\d+)\r?\n(.*?)'
                      + re.escape(marker) + '_END', serial, re.DOTALL)
    if not match or match.group(1) != '0':
        raise RuntimeError('Guest invocation failed or boot did not reach the trusted client')
    payload = base64.b64decode(re.sub(r'\s+', '', match.group(2)), validate=True)
    observations = [json.loads(line) for line in payload.splitlines() if line.strip()]
    if len(observations) != len(plan['steps']):
        raise RuntimeError('Incomplete guest observations')
    (OUTPUT / 'observations.json').write_text(json.dumps(observations, sort_keys=True) + '\n')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('build', 'run'):
        raise SystemExit('usage: entrypoint.py build|run')
    {'build': build, 'run': run}[sys.argv[1]]()
