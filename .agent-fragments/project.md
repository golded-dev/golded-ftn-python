# golded-ftn

This Python library owns shared FTN values, protocols and pure text helpers.
Concrete readers, writers, databases and ingest policy belong to consumers.

Preserve source bytes separately from decoded or repaired text. ControlLine.raw
is the loaded text line, including trailing nulls, without its line separator.
Keep routing strings unexpanded and unknown provenance as None. Preserve CP850
defaults and optional field meanings. Synthetic IDs cover the complete body and
are distinct from external MSGID and source record identity.

Keep public exports explicit and typed. Use frozen, slotted, keyword-only values
and tuples. File contracts accept str or PathLike. Text helpers accept str and
byte helpers accept bytes. Repair stays opt-in; confidence is a heuristic score.

Run Ruff lint and format checks, strict mypy and pytest for changes. For packaging,
build both archives, inspect metadata, rebuild from sdist and test an installed
wheel outside the checkout. Keep runtime dependencies empty. Compare public
changes with docs/php-api.md and protect relevant FTN scenarios with tests.

Edit this fragment or agent-compose.toml, then preview, build and check.
Commit, tag, publish and remote setup require an explicit request.

Strict reading stays the default. Archive mode requires an issue callback and
reports every recovery, skipped record and unsafe traversal stop. Keep source
paths, identities and byte offsets in issues; keep message contents out. Callback
failures propagate. Protect both modes with independent synthetic fixtures.
