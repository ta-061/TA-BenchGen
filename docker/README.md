# OP-TEE runtime image

Build from the repository root (Linux amd64 is the recorded benchmark platform):

```sh
docker build --platform linux/amd64 -f docker/Dockerfile -t ta-bench-runtime:4.4.0 .
docker image inspect ta-bench-runtime:4.4.0 --format '{{.Id}}'
```

Pass that immutable `sha256:...` ID to `ta-bench generate --image`. For a registry
image use `registry/repository@sha256:...`. The tool does not publish images or
invent a registry digest. Image creation fetches sources and toolchains and can
take tens of minutes and many GB; verification itself uses `--network none`.
`--build-arg JOBS=4` controls parallelism during image construction.

The Debian base is digest-pinned. The OP-TEE 4.4.0 manifest is fixed to
`8fb529424c83c85abce37c9c6936fd64fbbcd734`; git-repo is also commit-pinned.
Upstream's manifest chooses QEMU v8.1.2 and the toolchain makefile chooses Arm GNU
11.3.rel1. A built image's content digest is the final environment identity.
Distribution packages fetched during image construction may change; compare
image digests, not tags, between experiments. No registry image is bundled.

The build runs upstream's `qemu_v8.mk` and adds one statically linked generic
TEEC client and a fixed tee-supplicant event plugin. At verification time:

1. Copy the reference/candidate tree into a disposable container; build its
   `ta/Makefile` against the image's `export-ta_arm64` SDK. The Makefile must
   honor the standard OP-TEE `O` output directory. Build paths, source mtimes,
   locale, timezone and `SOURCE_DATE_EPOCH` are fixed between variants.
2. Put the resulting `.ta`, fixed client and input data in a new initramfs overlay.
3. Boot a fresh headless QEMU with software TCG, no networking, no KVM, and no
   persistent disk. Start `tee-supplicant` and the generic client.
4. Decode observations, retaining both serial logs under `work/`.

Runner 4.3.0 advertises `org.ta-bench.features="shared_memory_events_v1 output_reference_v1"`.
`output_reference_v1` lets an input copy bytes from an earlier invoke's output. Since 4.3.0 a value
parameter can be the source or the target too, read as eight bytes (a then b, little-endian); a
4.2.0 image rejects such a plan as an execution error.
Since 4.3.1 each temporary memref (`memref_*`) buffer lives in pages of its own (mmap) instead of
the heap. With dynamic shared memory libteec registers that buffer itself, OP-TEE maps its whole
pages into the TA, and the TA stack can sit directly below a parameter mapping. With heap buffers,
a TA writing past its stack or parameter overwrote the client's malloc metadata; the client then
aborted in `free()` and the step of a TA that OP-TEE reported as dead (`TEEC_ERROR_TARGET_DEAD`)
was lost as an execution error. Now the step is recorded, and an input buffer the TA overwrote
shows its contents after the call, as before. Bytes around a temporary memref on its pages read as
zero instead of client heap contents. `shared_memref_*` buffers are unchanged: libteec already
allocates them in whole pages.
If a local 4.4.0 image is already built, update only the trusted runner with:

```sh
docker image inspect ta-bench-runtime:4.4.0 --format '{{.Id}}'
docker build --pull=false -f docker/Dockerfile.runtime -t ta-bench-runtime:4.4.0-events .
export TA_BENCH_IMAGE=$(docker image inspect ta-bench-runtime:4.4.0-events --format '{{.Id}}')
```

`BASE_RUNTIME` may override the base tag or registry digest. Verify the local
base ID before building; Docker BuildKit does not accept a bare local image ID
as `FROM sha256:...`. Record/use the resulting immutable ID for experiments.
Old images still support ordinary plans, but DUS requests require the feature
label and are rejected before contacting the generation API if it is missing.

### Optional RPMB storage for AVB

The production request file includes `avb/ORDER`. Its upstream TA explicitly uses
`TEE_STORAGE_PRIVATE_RPMB`, so the ordinary runtime is insufficient. After the
runner update above, enable the software RPMB backend with:

```sh
docker build --pull=false -f docker/Dockerfile.rpmb -t ta-bench-runtime:4.4.0-rpmb .
export TA_BENCH_IMAGE=$(docker image inspect ta-bench-runtime:4.4.0-rpmb --format '{{.Id}}')
```

The extra build reuses the existing sources and toolchains, rebuilds OP-TEE and
the Arm Trusted Firmware boot artifacts, and freezes them with `finish_image.py`.
It preserves upstream build flags, including `O=out/arm`, so the rebuilt kernel
is the one copied into the runtime. `BASE_RUNTIME` can select another compatible
runner image. The base runtime tag is not changed.

The recipe enables `CFG_RPMB_FS`, `CFG_RPMB_WRITE_KEY`, and `CFG_RPMB_TESTKEY`.
The upstream rootfs already has `BR2_PACKAGE_OPTEE_CLIENT_EXT_RPMB_EMU=y`.
`CFG_REE_FS_INTEGRITY_RPMB=n` keeps the ordinary REE storage configuration.
The image adds `rpmb_storage_v1` to its feature label. This label lets the AVB
integration test select the image; the generator does not infer storage
requirements for arbitrary TA source. Select this image explicitly for AVB.

RPMB is emulated in the disposable QEMU instance and resets between input plans,
including repetitions and variants. This tests the TA's state-dependent ordering
within one execution. It does not establish physical RPMB replay resistance or
persistence across reboots. The recipe uses test keys for this emulator.

`examples/avb_order.json` provides a reproducible candidate: both versions reject
a decreasing rollback index with `TEE_ERROR_SECURITY`, but a following read
reveals that the defective version has already persisted the rejected value.
A control plan sends the identical write to fresh storage, where both versions
accept it: the rejection depends on the stored state, not on the parameters.
The QEMU test suite covers this case when run with the RPMB image.

### Shared-memory event execution

For event plans the host instruments temporary build copies with identical
statement checkpoints. The checkpoint calls `tee_invoke_supp_plugin`; the
fixed plugin contacts the client's UNIX socket worker. The worker checks and
modifies a `TEEC_AllocateSharedMemory` buffer while the TA is paused, records
the measured bytes, and acknowledges before the TA resumes. Registered partial
memrefs map that buffer into the TA; temporary memrefs are not used for events.
No arbitrary TA-private address is exposed. A missing event or failed RPC
invalidates execution. The source hashes and inserted locations remain under
`work/`; distributed source never contains these hooks.

Build and execution containers are non-root with a read-only root filesystem,
all capabilities dropped, no-new-privileges, per-operation mounts only, and
memory/CPU/process/time limits. Docker's client timeout is followed by explicit
container removal. An unreachable boot, timeout or missing observations is an
`execution_error`; it is never reported as a successful TA comparison.

On macOS / Apple Silicon use the same `--platform linux/amd64` image under
Docker emulation and `--development`. Only runs initiated on Linux amd64 can be
saved to `benchmark/defective/`. Native arm64 image builds are not supported by
this recipe: upstream 4.4.0 requires building the aarch64-host toolchain from
source instead of the amd64 download target. That path has not been verified.

Upstream implementation references:

- https://optee.readthedocs.io/en/latest/building/devices/qemu.html
- https://github.com/OP-TEE/manifest/blob/4.4.0/qemu_v8.xml
- https://github.com/OP-TEE/build/blob/4.4.0/qemu_v8.mk
- https://github.com/OP-TEE/build/blob/4.4.0/toolchain.mk
