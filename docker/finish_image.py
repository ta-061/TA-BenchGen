"""Freeze shared client binary and runtime boot artifacts at image build time."""
import shutil
import subprocess
from pathlib import Path

root = Path('/opt/optee')
compiler = next((root / 'toolchains/aarch64/bin').glob('aarch64*-gcc'))
subprocess.run(['make', '-C', str(root / 'optee_client'), 'build-libteec',
                'CROSS_COMPILE=' + str(compiler)[:-3], 'CFG_TEE_CLIENT_LOG_LEVEL=0'], check=True)
libs = list((root / 'optee_client').rglob('libteec.a'))
if not libs:
    raise RuntimeError('libteec.a was not produced')
subprocess.run([str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-static', '-I' + str(root / 'optee_client/libteec/include'),
                '/opt/ta-bench/invoke/main.c', str(libs[0]), '-lpthread',
                '-o', '/opt/ta-bench/ta-invoke'], check=True)
subprocess.run([str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-shared', '-fPIC', '-I' + str(root / 'optee_client/libteec/include'),
                '/opt/ta-bench/invoke/event_plugin.c', '-o', '/opt/ta-bench/events.plugin'], check=True)
# Dereference upstream build symlinks, so run containers never modify build tree.
boot = Path('/opt/ta-bench/boot')
boot.mkdir(exist_ok=True)
for name in ('bl1.bin', 'bl2.bin', 'bl31.bin', 'bl32.bin', 'bl32_extra1.bin',
             'bl32_extra2.bin', 'bl33.bin', 'Image', 'uImage', 'rootfs.cpio.gz'):
    source = root / 'out/bin' / name
    if source.exists():
        shutil.copyfile(source, boot / name)
qemu = list((root / 'qemu/build').rglob('qemu-system-aarch64'))
qemu = [p for p in qemu if p.is_file()]
if not qemu:
    raise RuntimeError('QEMU binary missing')
Path('/opt/ta-bench/qemu-path').write_text(str(qemu[0]))
