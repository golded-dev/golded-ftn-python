# Changelog

## 1.0.0 — Unreleased

Initial Python FTN core: immutable values, structural protocols, FTN addresses,
charset aliases, strict decoding, null-padded fields, body normalization,
control-line parsing and opt-in mojibake repair. Synthetic identity uses SHA-256
with the complete body. No runtime dependencies or concrete archive readers.

Before release: handle null-terminated charset declarations and FTN aliases in
fallback and mojibake candidates. MSGID extraction now shares the control parser's
quoting, casing and null rules. Contract tests use native filesystem paths.
