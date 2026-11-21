# TEEC invocation client

The runtime builds `main.c` once and uses the resulting client for both the reference and defective TAs. The container entry point translates a validated input sequence into session operations for the client. [Runtime image](../../../docker/README.md) · [Input format](../../../docs/candidate-format.md)

The client records the operation, result, error origin, parameter values, and whether OP-TEE reported `TEEC_ERROR_TARGET_DEAD`. The following conventions apply when reading the observations.

- A successful operation has error origin `0`.
- `TEEC_CloseSession` has no return value. A completed close is recorded with `result=0` and `origin=0`.
- A short-buffer response records the returned size and at most the bytes that fit in the allocated output buffer.
- A command on a session that failed to open returns `TEEC_ERROR_BAD_STATE`.

Incomplete guest output or a timeout produces an execution error. The runtime stores both normal-world and secure-world serial logs in `work/`.
