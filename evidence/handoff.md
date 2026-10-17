# R1 Handoff Report: `golded-ftn` `1.3.0` Recoverable Writer Primitives

## Scope and Governance Verification
- **Worktree:** `/Users/odinn/Projects/golded-dev/ftn-node-work/worktrees/golded-ftn-python-r1/`
- **Main checkout untouched:** `/Users/odinn/Projects/golded-dev/golded-ftn-python/` and `/Users/odinn/Projects/golded-dev/ftn-plan.html` were not modified.
- **No git commit or publication performed.**
- **Runtime dependencies:** `dependencies = []` (stdlib only).
- **Authoritative contract:** `/Users/odinn/Projects/golded-dev/ftn-node-work/contracts/recovery-v1.md` (amended frozen contract).
- **Review addressed:** `/Users/odinn/Projects/golded-dev/ftn-node-work/reviews/r1-claude-review.txt` required implementation fixes B1, B2, D1–D6, D11, D13, S1, S2/S3, S6.

## Summary of Changes
1. **Version Bump (`pyproject.toml`):**
   - Bumped `golded-ftn` version from `1.2.2` to `1.3.0` with zero runtime dependencies.
2. **`RollbackError` Sanitization (`src/golded_ftn/_writer_io.py`):**
   - `str(error)` is always `"Transaction rollback failed during <operation>"`. Empty operation uses the documented fallback code `rollback`. Exception chaining uses `from None`.
3. **Public Recoverable Writer Types & Protocols (`src/golded_ftn/models.py`, `src/golded_ftn/contracts.py`, `src/golded_ftn/__init__.py`):**
   - Exported `CommitState`, `RecoveryOperationKind`, `PhysicalBaseIdentity`, `RecoveryReference`, `PreparedMutation`, `OfflineRecoveryAssertion`, `RecoveryError`, `RecoverableWriterSession`, and `RecoverableMessageBaseWriter`.
   - `RecoveryError.__reduce__` pickles by `code` only (D13). Closed codes never interpolate paths.
4. **Durable Recovery Engine (`src/golded_ftn/_recovery.py`) matching the amended contract:**
   - **B1:** Deleted `_is_prefix_or_zero_extension`. Without `own_created_inode`, an `existed=False` target is owned only if `len(cur) > 0` and `planned_new_bytes.startswith(cur)`. Empty and zero-extended files raise `foreign_target_occupied` and are never unlinked. Inode is rechecked immediately before unlink.
   - **B2:** Retained descriptors are keyed by `(st_dev, st_ino)`, `plan.fd` is persisted, `rel_path` is normalized, and any `os.open`/`os.close` of `physical_base.lock_inode` raises `RecoveryError`.
   - **D1:** `applied=True` is set only after `apply_fn()` returns. Failed apply keeps the slot apply-failed so `settle(..., COMMITTED)` is `invalid_prepared_mutation` without poisoning; `UNCOMMITTED` restore remains allowed.
   - **D2:** `recover` resolves every pending transaction first. Exceptions from `resolve` become `unknown_commit_state` and poison. Any `UNKNOWN` poisons and leaves all artifacts and base files untouched.
   - **D3:** `load_ready_manifest` compares manifest `lock_inode` with `physical_base.lock_inode`.
   - **D4:** Two-way `os.path.commonpath` containment between recovery root and every registered base root (`unsafe_recovery_path`).
   - **D5:** `prepare` requires `isinstance(transaction_id, uuid.UUID)` and `version == 4`.
   - **D6:** `initialize_recovery_root` writes `.base-binding.json` atomically (tmp → fsync → replace → fsync dir) and fails closed if transaction artifacts already exist while the binding is being created.
   - **S1:** `LockTimeoutError` uses the fixed message `"Timed out locking base"`.
   - **S6:** Symlink ancestors above the resolved root are not rejected; symlink rejection is limited to registered roots / `recovery_root` last components and paths under them.
   - **S2/S3:** Escaping `OSError` is wrapped as `RecoveryError` with a closed code and `from None`; optional private `_cause` is not shown in `str`/`repr`.
5. **Tests (`tests/test_recovery.py`, `tests/test_writer_io.py`):**
   - Empty / zero-filled `existed=False` targets without `own_created_inode` → `foreign_target_occupied`, file survives.
   - `apply_fn` raises then `settle(COMMITTED)` is rejected; `UNCOMMITTED` still restores.
   - Two pending txs COMMITTED then UNKNOWN: resolve-all-first; artifacts and base files unchanged. `resolve` exceptions poison without mutation.
   - Manifest `lock_inode` mismatch → `corrupt_recovery_manifest`.
   - Non-UUIDv4 and path-like `"../x"` transaction ids rejected.
   - Nested `recovery_root` inside a base root → `unsafe_recovery_path`.
   - `LockTimeoutError` `str`/`repr` contain no filesystem path.
   - `RecoveryError` pickle round-trip.

## Verification Commands & Results
- `.venv/bin/pytest -q`: **213 passed**
- `.venv/bin/ruff check src tests`: **All checks passed**
- `.venv/bin/ruff format --check src tests`: **17 files already formatted**
- `.venv/bin/mypy --strict src tests scripts`: **Success: no issues found in 18 source files**

## Remaining gaps (review items not in this required fix set)
- **D7/D8/D9/D10/D12/D14:** documented as low/perf or contract-note items; not changed here.
- **S4:** operation-code allowlist for `RollbackError` not added.
- **S5:** recovery-root owner / refuse-chmod-on-foreign-dir not added.
- **S7/S8:** remaining same-user TOCTOU and internal `repr()` of `rel_path` not expanded beyond the required unlink inode recheck.
- Crash-injection matrix, property tests for `_outside_ranges_match`, umask/foreign-owner permission tests, and full assertion-replay matrix from the review test list were not added beyond the required cases.
