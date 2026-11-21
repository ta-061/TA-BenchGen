import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ta_bench.errors import ExecutionError
from ta_bench.runtime.docker import DockerRunner
from ta_bench.runtime.ta_uuid import discover_uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('container_entry', ROOT / 'docker/entrypoint.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def test_sample_uuid():
    assert discover_uuid(ROOT / 'benchmark/normal/secure_kv') == 'd987bb20-2323-4a70-9d97-717255082611'


def test_uuid_ambiguity(tmp_path):
    (tmp_path / 'x.h').write_text('#define FIRST_UUID "d987bb20-2323-4a70-9d97-717255082611"\n'
                                '#define SECOND_UUID "d987bb20-2323-4a70-9d97-717255082612"\n')
    with pytest.raises(ExecutionError, match='found 2'):
        discover_uuid(tmp_path)
    # A TA that also names the UUID of another TA is resolved through its TA_UUID alias.
    (tmp_path / 'user_ta_header_defines.h').write_text('#define TA_UUID SECOND_UUID\n')
    assert discover_uuid(tmp_path) == 'd987bb20-2323-4a70-9d97-717255082612'


def test_uuid_symlink(tmp_path):
    (tmp_path / 'x.h').symlink_to('/etc/passwd')
    with pytest.raises(ExecutionError, match='Symbolic'):
        discover_uuid(tmp_path)


def image_info():
    return [{'Id': 'sha256:' + 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64',
             'Config': {'Labels': {'org.ta-bench.' + key: 'test' for key in
                                  ('optee_revision', 'qemu_revision', 'runner_version', 'toolchain')}}}]


def test_runtime_requires_pinned_image(tmp_path):
    with pytest.raises(ExecutionError, match='immutable'):
        DockerRunner('some:tag', tmp_path)


def test_runtime_container_is_offline_and_bounded(tmp_path, monkeypatch):
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(image_info()), '')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    runner = DockerRunner('sha256:' + 'a' * 64, tmp_path)
    command = runner._command('test-name', tmp_path / 'in', tmp_path / 'out', 'run')
    assert command[command.index('--network') + 1] == 'none'
    assert '--read-only' in command and '--privileged' not in command
    assert command[command.index('--cap-drop') + 1] == 'ALL'
    assert command[command.index('--memory') + 1] == '4g'
    assert 'no-new-privileges' in command
    assert all('/var/run/docker.sock' not in arg for arg in command)
    assert runner.environment['image_digest'] == 'sha256:' + 'a' * 64


def test_timeout_removes_container(tmp_path, monkeypatch):
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ['docker', 'image', 'inspect']:
            return subprocess.CompletedProcess(command, 0, json.dumps(image_info()), '')
        if command[:2] == ['docker', 'run']:
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    runner = DockerRunner('sha256:' + 'a' * 64, tmp_path)
    with pytest.raises(ExecutionError):
        runner._execute(tmp_path, tmp_path / 'out', 'run')
    assert calls[-1][:3] == ['docker', 'rm', '-f']


def test_development_never_publishable(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(image_info())))
    runner = DockerRunner('test:tag', tmp_path, development=True)
    assert runner.publishable is False
    assert runner.image == 'sha256:' + 'a' * 64


@pytest.mark.parametrize('damage', ['metadata', 'metadata_type', 'missing', 'changed', 'symlink'])
def test_damaged_build_cache_is_rebuilt_without_erasing_evidence(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(image_info())))
    runner = DockerRunner('sha256:' + 'a' * 64, tmp_path / 'runner')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'entry.c').write_text('int value;\n')
    calls = []

    def build_output(_source, output, mode):
        assert mode == 'build'
        calls.append(output)
        output.mkdir(parents=True)
        (output / 'sample.ta').write_bytes(b'fresh artifact')

    monkeypatch.setattr(runner, '_execute', build_output)
    artifact = runner.build(source)
    assert runner.build(source) == artifact
    assert len(calls) == 1
    if damage == 'metadata':
        (artifact.parent / 'artifact.json').write_text('{')
    elif damage == 'metadata_type':
        (artifact.parent / 'artifact.json').write_text('[]')
    elif damage == 'missing':
        shutil.rmtree(artifact)
    elif damage == 'changed':
        (artifact / 'sample.ta').write_bytes(b'corrupt artifact')
    else:
        (artifact / 'sample.ta').unlink()
        (artifact / 'sample.ta').symlink_to(source / 'entry.c')
    rebuilt = runner.build(source)
    assert len(calls) == 2 and rebuilt != artifact
    assert (rebuilt / 'sample.ta').read_bytes() == b'fresh artifact'
    assert artifact.parent.is_dir()


def plan(params=None):
    return {'uuid': 'd987bb20-2323-4a70-9d97-717255082611', 'steps': [
        {'op': 'open', 'session': 's'},
        {'op': 'invoke', 'session': 's', 'command_id': 0,
         'params': params or [{'type': 'value_inout', 'a': 2, 'b': 7}] + [{'type': 'none'}] * 3},
        {'op': 'close', 'session': 's'}]}


def test_line_encoding_is_data():
    encoded = entry.encode_plan(plan()).decode().splitlines()
    assert encoded[0] == 'O 0 d987bb20-2323-4a70-9d97-717255082611'
    assert encoded[1] == 'I 0 0 3 2 7 0 - 0 0 0 0 - 0 0 0 0 - 0 0 0 0 -'
    assert encoded[2] == 'C 0'


def test_memory_limits():
    params = [{'type': 'memref_output', 'size': 2**30}] + [{'type': 'none'}] * 3
    with pytest.raises(ValueError, match='size'):
        entry.encode_plan(plan(params))


def test_cpio_overlay_contains_regular_files_and_alignment():
    data = entry.cpio_overlay({'ta-bench/init': b'#!/bin/sh\n'})
    assert data.startswith(b'070701') and len(data) % 512 == 0
    assert b'ta-bench/init\0' in data and b'TRAILER!!!\0' in data


@pytest.fixture
def client(tmp_path):
    if not shutil.which('cc'):
        pytest.skip('C compiler not installed')
    (tmp_path / 'tee_client_api.h').write_text(r'''
#include <stddef.h>
#include <stdint.h>
typedef uint32_t TEEC_Result;
typedef struct { int x; } TEEC_Context;
typedef struct { int x; } TEEC_Session;
typedef struct { uint32_t timeLow; uint16_t timeMid, timeHiAndVersion; uint8_t clockSeqAndNode[8]; } TEEC_UUID;
typedef struct { void *buffer; size_t size; uint32_t flags; } TEEC_SharedMemory;
typedef union { struct { uint32_t a,b; } value; struct { void *buffer; size_t size; } tmpref;
 struct { TEEC_SharedMemory *parent; size_t size, offset; } memref; } TEEC_Parameter;
typedef struct { uint32_t paramTypes; TEEC_Parameter params[4]; } TEEC_Operation;
#define TEEC_SUCCESS 0
#define TEEC_ERROR_BAD_STATE 0xffff0007U
#define TEEC_ERROR_TARGET_DEAD 0xffff3024U
#define TEEC_ORIGIN_API 1
#define TEEC_LOGIN_PUBLIC 0
#define TEEC_MEM_INPUT 1
#define TEEC_MEM_OUTPUT 2
TEEC_Result TEEC_AllocateSharedMemory(TEEC_Context *, TEEC_SharedMemory *);
void TEEC_ReleaseSharedMemory(TEEC_SharedMemory *);
TEEC_Result TEEC_InitializeContext(const char *, TEEC_Context *);
TEEC_Result TEEC_OpenSession(TEEC_Context *, TEEC_Session *, const TEEC_UUID *, uint32_t, void *, TEEC_Operation *, uint32_t *);
TEEC_Result TEEC_InvokeCommand(TEEC_Session *, uint32_t, TEEC_Operation *, uint32_t *);
void TEEC_CloseSession(TEEC_Session *);
void TEEC_FinalizeContext(TEEC_Context *);
''')
    (tmp_path / 'stub.c').write_text(r'''
#include "tee_client_api.h"
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include "event_protocol.h"
TEEC_Result TEEC_AllocateSharedMemory(TEEC_Context *c, TEEC_SharedMemory *m) {
 (void)c; m->buffer=calloc(m->size ? m->size : 1,1); return m->buffer ? 0 : 0xffff000cU;
}
void TEEC_ReleaseSharedMemory(TEEC_SharedMemory *m) { free(m->buffer); }
static void checkpoint(uint32_t id) {
 int fd=socket(AF_UNIX,SOCK_STREAM,0); uint32_t answer=1;
 struct sockaddr_un address={.sun_family=AF_UNIX}; strcpy(address.sun_path,TB_EVENT_SOCKET);
 if (fd<0 || connect(fd,(struct sockaddr *)&address,sizeof(address)) ||
     send(fd,&id,sizeof(id),0)!=sizeof(id) || recv(fd,&answer,sizeof(answer),MSG_WAITALL)!=sizeof(answer)) exit(3);
 close(fd);
}
TEEC_Result TEEC_InitializeContext(const char *x, TEEC_Context *c) { (void)x; (void)c; return 0; }
TEEC_Result TEEC_OpenSession(TEEC_Context *c, TEEC_Session *s, const TEEC_UUID *u, uint32_t l, void *d, TEEC_Operation *o, uint32_t *r) { (void)c;(void)s;(void)u;(void)l;(void)d;(void)o;*r=4;return 0; }
TEEC_Result TEEC_InvokeCommand(TEEC_Session *s, uint32_t cmd, TEEC_Operation *o, uint32_t *r) {
 (void)s; *r=4;
 if (cmd == 76 || cmd == 77) {
  if (cmd == 77) for (uint32_t i=0;i<o->params[2].value.b;i++) checkpoint(o->params[2].value.a);
  memcpy(&o->params[1].value.a,o->params[0].memref.parent->buffer,4); return 0;
 }
 if (cmd == 99) return TEEC_ERROR_TARGET_DEAD;
 if (cmd == 98) {
  /* OP-TEE maps whole pages of a registered buffer: a TA overflowing into that mapping can
     overwrite everything on the buffer's page, as the sha stack overflow did. */
  for (int i=0;i<2;i++) memset((void *)((uintptr_t)o->params[i].tmpref.buffer & ~(uintptr_t)4095),0x5a,4096);
  return TEEC_ERROR_TARGET_DEAD;
 }
 if ((o->paramTypes & 15) == 6) { if(o->params[0].tmpref.size) ((char *)o->params[0].tmpref.buffer)[0]='A'; o->params[0].tmpref.size=100; return 0xffff0010U; }
 o->params[0].value.b += 1; return 0;
}
void TEEC_CloseSession(TEEC_Session *s) { (void)s; }
void TEEC_FinalizeContext(TEEC_Context *s) { (void)s; }
''')
    binary = tmp_path / 'client'
    import uuid
    socket_path = Path('/tmp') / ('tb-test-' + uuid.uuid4().hex + '.sock')
    subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-pthread', '-DTB_EVENT_SOCKET="' + str(socket_path) + '"',
                    '-I' + str(tmp_path), '-I' + str(ROOT / 'src/ta_bench/invoke'),
                    str(ROOT / 'src/ta_bench/invoke/main.c'),
                    str(tmp_path / 'stub.c'), '-o', str(binary)], check=True)
    yield binary
    socket_path.unlink(missing_ok=True)


def test_common_c_client_values(client):
    proc = subprocess.run([str(client)], input=entry.encode_plan(plan()), capture_output=True, check=True)
    data = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(data) == 3 and data[1]['params'][0]['b'] == 8
    assert data[1]['origin'] == 0 and data[1]['ta_crashed'] is False


def test_common_c_client_short_buffer_is_bounded(client):
    p = plan([{'type': 'memref_output', 'size': 1}] + [{'type': 'none'}] * 3)
    proc = subprocess.run([str(client)], input=entry.encode_plan(p), capture_output=True, check=True)
    data = [json.loads(line) for line in proc.stdout.splitlines()]
    assert data[1]['params'][0] == {'type': 'memref_output', 'size': 100, 'data': '41'}


def test_common_c_client_panic(client):
    p = plan()
    p['steps'][1]['command_id'] = 99
    proc = subprocess.run([str(client)], input=entry.encode_plan(p), capture_output=True, check=True)
    data = [json.loads(line) for line in proc.stdout.splitlines()]
    assert data[1]['ta_crashed'] is True and data[1]['result'] == 0xffff3024


def test_common_c_client_survives_a_ta_overwriting_its_parameter_pages(client):
    # Before 4.3.1 the buffers were heap blocks: overwriting their pages destroyed malloc
    # metadata, the client aborted in free() and the dead TA's step was never recorded.
    p = plan([{'type': 'memref_input', 'data': '01' * 12}, {'type': 'memref_input', 'data': '00', 'size': 4000},
              {'type': 'none'}, {'type': 'none'}])
    p['steps'][1]['command_id'] = 98
    proc = subprocess.run([str(client)], input=entry.encode_plan(p), capture_output=True, check=True)
    data = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(data) == 3 and data[1]['ta_crashed'] is True and data[1]['result'] == 0xffff3024
    # The client reports its input buffers after the call, so the overwrite stays visible.
    assert data[1]['params'][0] == {'type': 'memref_input', 'size': 12, 'data': '5a' * 12}
    assert data[1]['params'][1]['size'] == 4000 and data[1]['params'][1]['data'] == '5a' * 4000


def reference_plan(inserts, source_type='memref_output'):
    none = {'type': 'none'}
    return {'uuid': 'd987bb20-2323-4a70-9d97-717255082611', 'steps': [
        {'op': 'open', 'session': 's'},
        {'op': 'invoke', 'session': 's', 'command_id': 0,
         'params': [{'type': source_type, 'size': 4}, none, none, none]},
        {'op': 'invoke', 'session': 's', 'command_id': 0,
         'params': [{'type': 'value_inout'},
                    {'type': 'memref_input', 'data': 'ffffffffffff', 'size': 6, 'inserts': inserts}, none, none]},
        {'op': 'close', 'session': 's'}]}


def test_common_c_client_copies_an_earlier_output_into_a_later_input(client):
    from ta_bench.runtime.events import OUTPUT_REFERENCE, required_features
    p = reference_plan([{'offset': 2, 'from': {'step': 2, 'param': 0, 'offset': 0, 'length': 2}}])
    assert required_features(p['steps']) == {OUTPUT_REFERENCE}
    encoded = entry.encode_plan(p)
    assert b'\nK 0\n' in encoded and b'\nR 1 2 2 0 0 2\n' in encoded
    proc = subprocess.run([str(client)], input=encoded, capture_output=True, check=True)
    data = [json.loads(line) for line in proc.stdout.splitlines()]
    # The stub writes 'A' (0x41) at the start of the 4-byte output; the rest stays zero.
    assert data[1]['params'][0]['data'] == '41000000'
    assert data[2]['params'][1] == {'type': 'memref_input', 'size': 6, 'data': 'ffff4100ffff'}


def value_reference_plan(target_type, inserts):
    none = {'type': 'none'}
    return {'uuid': 'd987bb20-2323-4a70-9d97-717255082611', 'steps': [
        {'op': 'open', 'session': 's'},
        {'op': 'invoke', 'session': 's', 'command_id': 0,
         'params': [{'type': 'value_inout', 'a': 7, 'b': 41}, none, none, none]},
        {'op': 'invoke', 'session': 's', 'command_id': 0,
         'params': [{'type': target_type, 'inserts': inserts}, none, none, none]},
        {'op': 'close', 'session': 's'}]}


def test_common_c_client_copies_an_earlier_value_into_a_later_value(client):
    # A value parameter is eight bytes, a then b: the handle a TA returned in b becomes the next a.
    p = value_reference_plan('value_input', [{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 4, 'length': 4}}])
    proc = subprocess.run([str(client)], input=entry.encode_plan(p), capture_output=True, check=True)
    data = [json.loads(line) for line in proc.stdout.splitlines()]
    # The stub adds one to b of the first parameter.
    assert data[1]['params'][0] == {'type': 'value_inout', 'a': 7, 'b': 42}
    assert data[2]['params'][0] == {'type': 'value_input', 'a': 42, 'b': 1}


@pytest.mark.parametrize('target_type,inserts,message', [
    ('value_output', [{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 4, 'length': 4}}], 'input or inout'),
    ('value_input', [{'offset': 6, 'from': {'step': 2, 'param': 0, 'offset': 4, 'length': 4}}], 'exceeds this parameter'),
    ('value_input', [{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 6, 'length': 4}}], 'source range'),
])
def test_value_references_are_checked_before_execution(target_type, inserts, message):
    from ta_bench.candidate.plan import validate_steps
    from ta_bench.errors import ValidationError
    with pytest.raises(ValidationError, match=message):
        validate_steps(value_reference_plan(target_type, inserts)['steps'])


@pytest.mark.parametrize('inserts,source_type,message', [
    ([{'offset': 0, 'from': {'step': 3, 'param': 0, 'offset': 0, 'length': 1}}], 'memref_output', 'earlier invoke'),
    ([{'offset': 0, 'from': {'step': 1, 'param': 0, 'offset': 0, 'length': 1}}], 'memref_output', 'earlier invoke'),
    ([{'offset': 0, 'from': {'step': 2, 'param': 1, 'offset': 0, 'length': 1}}], 'memref_output', 'output or inout'),
    ([{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 0, 'length': 1}}], 'memref_input', 'output or inout'),
    ([{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 2, 'length': 3}}], 'memref_output', 'source range'),
    ([{'offset': 5, 'from': {'step': 2, 'param': 0, 'offset': 0, 'length': 2}}], 'memref_output', 'exceeds this parameter'),
    ([{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 0, 'length': 0}}], 'memref_output', 'source range'),
    ([{'offset': 0, 'from': {'step': 2, 'param': 0, 'offset': 0}}], 'memref_output', 'insert needs'),
    ([], 'memref_output', 'inserts must contain'),
])
def test_output_references_are_checked_before_execution(inserts, source_type, message):
    from ta_bench.candidate.plan import validate_steps
    from ta_bench.errors import ValidationError
    with pytest.raises(ValidationError, match=message):
        validate_steps(reference_plan(inserts, source_type)['steps'])


@pytest.mark.qemu
def test_real_qemu_smoke_when_image_is_supplied(tmp_path):
    """Opt in explicitly: TA_BENCH_TEST_IMAGE=sha256:... uv run pytest -k real_qemu."""
    import os
    image = os.environ.get('TA_BENCH_TEST_IMAGE')
    if not image:
        pytest.skip('set TA_BENCH_TEST_IMAGE to a locally available pinned runtime image')
    runner = DockerRunner(image, tmp_path, timeout=300)
    source = ROOT / 'benchmark/normal/secure_kv'
    artifact = runner.build(source)
    candidate = json.loads((ROOT / 'examples/secure_kv_ivw.json').read_text())
    normal_steps = candidate['tests'][0]['steps']
    first = runner.run(artifact, normal_steps, discover_uuid(source))
    second = runner.run(artifact, normal_steps, discover_uuid(source))
    assert first == second
    assert all(step['result'] == 0 for step in first)
    assert first[2]['params'][0]['b'] == 17
