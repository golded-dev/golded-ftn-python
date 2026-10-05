# Changelog

## Unreleased

Preserve literal degree and temperature signs during opt-in mojibake repair,
including lines that also contain DOS or UTF-8-as-Latin-1 damage.

## 1.2.0 — 2026-10-05

Add writer sessions, record identities, byte revisions, explicit patches and
writer errors. Outgoing messages now carry reply links and routing. Shared
internal I/O supports record locks, strict encoding and in-place rollback.

## 1.1.0 — Unreleased

Add immutable `ReaderIssue` and explicit archive options. Archive mode requires
a report callback; strict options remain the default.

## 1.0.0 — Unreleased

Initial Python FTN core: immutable values, structural protocols, FTN addresses,
charset aliases, strict decoding, null-padded fields, body normalization,
control-line parsing and opt-in mojibake repair. Synthetic identity uses SHA-256
with the complete body. No runtime dependencies or concrete archive readers.

Before release: handle null-terminated charset declarations and FTN aliases in
fallback and mojibake candidates. MSGID extraction now shares the control parser's
quoting, casing and null rules. Contract tests use native filesystem paths.
