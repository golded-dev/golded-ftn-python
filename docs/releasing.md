# Release checks

The authoritative version is in `pyproject.toml`. Build metadata follows the
[PyPA guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
The PyPI project endpoint returned HTTP 404 during the local release check.
CI contains no publish job.

Run the contributing checks, then `uv build` and `uv run twine check dist/*`.
Inspect wheel/sdist metadata and contents. Extract the sdist into a temporary
folder and rebuild with `uv build --wheel`. Install that wheel without runtime
dependencies in a clean environment outside the checkout. Run the tests and
README and API examples against the installed package, and strict mypy on a consumer.
Update `docs/api.md` for every public export/signature/field change and synchronize
the shared guide's core reference before publishing documentation.

CI covers Linux Python 3.12–3.14 with lint, format, typing and tests; Windows and
macOS run tests on 3.14. CI configuration is not evidence those jobs passed.
Record exact local interpreters and platforms in the handoff.

Before public release, confirm the package-index destination. The GitHub
repository is public and private vulnerability reporting is enabled. Review the generated AGENTS.md for public
suitability. Tags, remote creation and publication need explicit authorization.

## Local 1.2.0 release candidate — 2026-10-05

Verified on macOS 27.0 arm64 with CPython 3.14.6. The checkout contains
uncommitted changes; these checks cover the working tree, not a tagged release.

- `uv sync --locked`: passed.
- Ruff lint and format checks, strict mypy: passed.
- `uv run pytest -q`: 127 passed, 0 skipped.
- `uv build` and `uv run twine check dist/*`: passed for wheel and sdist.
- `scripts/verify_distribution.py`: passed metadata and package-content checks,
  byte comparison against a wheel rebuilt from sdist, isolated installed-package
  tests and strict consumer typing. Format packages also pass installed stubtest.
- `agent-compose check`: passed using the local mostly-agents tool.
- `git diff --check`: passed (whitespace only).

GitHub's API reports the repository as public and private vulnerability reporting
as enabled. PyPI's project JSON endpoint returned HTTP 404 on this date. No package
was uploaded. Local checks do not establish Linux/Windows or remote CI results.
GoldED build interoperability remains deferred; concurrent use stays disabled.

Release order: publish `golded-ftn==1.2.0` first, then the four format packages.
Each format package requires `golded-ftn>=1.2.0,<2`. Before publication, commit
and review CI for these exact sources, create the intended release tag, and
confirm the package-index destination and publishing authority. After core is
available, verify resolution from that index without local uv sources. Publish
only the reviewed archives, then check public installation and update the shared
guide's commit pins to the released commits. These remote actions are not part
of this local preparation.

Archive checksums are recorded separately in `RELEASE-SHA256.txt` at the
repository root, outside the archives, after the final build.
