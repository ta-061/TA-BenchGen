# Common TEEC invocation client

`main.c` is compiled once into the immutable runtime image and reused for every
TA variant. `docker/entrypoint.py` converts validated JSON input to a bounded
ASCII line protocol (`O`/`I`/`C`, numeric session IDs, command ID, four parameters).
Optional `M checkpoint occurrence param offset expect_hex data_hex` lines must
immediately precede their `I` line. They schedule up to 16 checked shared-memory
writes during that invocation and do not create separate observation rows.
Memrefs use hexadecimal bytes, at most 1 MiB per parameter. Up to 32 session IDs
and 1024 steps are supported. No commands or executable code come from the AI.

Each O/I/C line yields JSON with the operation, result, error origin, parameter values
and `ta_crashed` (TEEC_ERROR_TARGET_DEAD). Origin is normalized to zero on success,
where Client API does not specify an error origin. Short-buffer outputs record
the returned size but read at most the allocated size. The wrapper treats failed
context initialization, incomplete output and timeouts as execution errors.

Guest output is written to a file, then transferred as base64 between random
markers on the normal-world serial console. Secure-world logs use a separate
serial file. Both serial logs remain in `work/`, outside benchmark observations.

`TEEC_CloseSession` has no result value; a completed close is represented by
`result=0, origin=0`. A command after a failed open is reported as the client's
`TEEC_ERROR_BAD_STATE` without dereferencing an uninitialized session. These are
fixed harness conventions, identical in both variants. A panic that is visible
only during a void close operation is not independently observable through the
Client API; witness inputs should invoke a command to observe the failure.

Kinds 8/9/10 allocate shared input/output/inout memory and map it using partial
registered memrefs. `events.h` owns a bounded socket worker; `event_plugin.c`
bridges tee-supplicant RPCs to that worker; `checkpoint.h` is injected only into
temporary TA build copies. The event handshake uses a fixed plugin UUID and a
checkpoint ID derived from the frozen source location. Each invocation resets
occurrence counts. Expected bytes, bounds, event order and completion are
checked. Successful events append measured before/after receipts to the invoke
row; failed schedules terminate the client without a valid observation sequence.
