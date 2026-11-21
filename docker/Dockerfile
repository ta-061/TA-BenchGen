# Build from the repository root: docker build -f docker/Dockerfile -t ta-bench-runtime:4.4.0 .
# Only image creation uses the network. Verification containers are offline.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
ARG OPTEE_MANIFEST_REVISION=8fb529424c83c85abce37c9c6936fd64fbbcd734
ARG JOBS=4
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake bc bison build-essential ca-certificates ccache cmake cpio curl \
    device-tree-compiler expect flex gawk git libattr1-dev libcap-ng-dev libffi-dev \
    libglib2.0-dev libgmp-dev libmpc-dev libmpfr-dev libncurses-dev libpixman-1-dev \
    libslirp-dev libssl-dev libtool libtool-bin libusb-1.0-0-dev make ninja-build openssh-client \
    patch python3 python3-cryptography python3-pip python3-pyelftools python3-pexpect \
    python3-venv rsync unzip uuid-dev wget xz-utils zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v2.48 https://gerrit.googlesource.com/git-repo /opt/git-repo \
    && test "$(git -C /opt/git-repo rev-parse HEAD)" = 454fdaf1191c87e5c770ab865a911e10e600e178 \
    && ln -s /opt/git-repo/repo /usr/local/bin/repo
RUN useradd --create-home --uid 1000 builder && mkdir /opt/optee && chown builder:builder /opt/optee
USER builder
WORKDIR /opt/optee
RUN git config --global user.email build@localhost && git config --global user.name ta-bench \
    && repo init --repo-rev=454fdaf1191c87e5c770ab865a911e10e600e178 -u https://github.com/OP-TEE/manifest.git -b "$OPTEE_MANIFEST_REVISION" -m qemu_v8.xml --depth=1 \
    && repo sync -c -j4 build buildroot linux optee_os optee_client optee_test optee_examples qemu trusted-firmware-a u-boot mbedtls
RUN make -C build -j"$JOBS" aarch32-toolchain aarch64-toolchain RUST_ENABLE=n
RUN make -C build -j"$JOBS" all RUST_ENABLE=n QEMU_VIRTFS_ENABLE=y QEMU_USERNET_ENABLE=n \
    BR2_PACKAGE_OPTEE_EXAMPLES_EXT=n BR2_PACKAGE_OPTEE_TEST_EXT=n
USER root
COPY src/ta_bench/invoke /opt/ta-bench/invoke
COPY src/ta_bench /opt/ta-bench/python/ta_bench
COPY docker/entrypoint.py /opt/ta-bench/entrypoint.py
COPY docker/finish_image.py /opt/ta-bench/finish_image.py
RUN python3 /opt/ta-bench/finish_image.py
ENV PATH="/opt/optee/toolchains/aarch64/bin:${PATH}"
LABEL org.ta-bench.runner_version="4.1.0" \
      org.ta-bench.features="shared_memory_events_v1" \
      org.ta-bench.optee_revision="4.4.0" \
      org.ta-bench.qemu_revision="v8.1.2" \
      org.ta-bench.toolchain="arm-gnu-toolchain-11.3.rel1" \
      org.ta-bench.manifest_revision="8fb529424c83c85abce37c9c6936fd64fbbcd734"
USER 1000:1000
WORKDIR /tmp
ENTRYPOINT ["python3", "/opt/ta-bench/entrypoint.py"]
