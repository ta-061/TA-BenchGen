# OP-TEE/QEMU runtime

The generator builds each TA in a Docker container and runs it in a disposable OP-TEE 4.4.0 guest. Building the image requires Docker and network access. Verification runs offline. Run the following commands from the repository root.

## Build the image

```sh
docker build --platform linux/amd64 -f docker/Dockerfile -t ta-bench-runtime:4.4.0 .
export TA_BENCH_IMAGE="$(docker image inspect --format '{{.Id}}' ta-bench-runtime:4.4.0)"
```

`TA_BENCH_IMAGE` identifies the exact runtime to use and record in `verification.json`. You can also pass a local image ID (`sha256:…`) or a registry digest (`repository@sha256:…`) with `--image`. The Dockerfile pins the OP-TEE manifest and builds the SDK, QEMU, and the guest. [Dockerfile](Dockerfile) · [OP-TEE build manifest](https://github.com/OP-TEE/manifest/blob/8fb529424c83c85abce37c9c6936fd64fbbcd734/qemu_v8.xml)

Linux amd64 is the host platform for saving verified benchmark cases. On macOS or arm64, use the linux/amd64 image and `--development`. The generator writes development results to `work/`.

## Runtime variants

| Image recipe | When to use it |
| --- | --- |
| [Dockerfile.runtime](Dockerfile.runtime) | Refresh the runner on an existing base image or use references to earlier outputs in an input sequence. |
| [Dockerfile.rpmb](Dockerfile.rpmb) | Use emulated RPMB storage, as required by the AVB reference TA. RPMB state resets for each input sequence. |

Build the runner update on top of the base image. For RPMB, build the storage variant on top of that update.

```sh
docker build --platform linux/amd64 --pull=false -f docker/Dockerfile.runtime -t ta-bench-runtime:4.4.0-events .
docker build --platform linux/amd64 --pull=false -f docker/Dockerfile.rpmb -t ta-bench-runtime:4.4.0-rpmb .
```

Set `TA_BENCH_IMAGE` to the ID of the variant you intend to use. The guest uses the same client to observe both implementations. [Client observations](../src/ta_bench/invoke/README.md)
