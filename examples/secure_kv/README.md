# Secure KV reference TA

This small reference keeps eight `uint32_t` values separately for each session.
It is a comparison baseline, not a claim of absence of defects.

UUID: `d987bb20-2323-4a70-9d97-717255082611`.
Open a public session with no parameters. Invoke with
`[value_inout(a=index,b=value), none, none, none]`.
Command `0` stores `b`; command `1` reads the slot into `b`.
Indices `0..7` are allowed; other indices return `TEE_ERROR_BAD_PARAMETERS`.
Close releases that session's state. Every QEMU boot starts from a fresh image.
The common runner builds `ta/Makefile`; no TA-specific host driver is required.
