# Release checks

The authoritative version is in `pyproject.toml`. Build metadata follows the
[PyPA guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
The manual `publish.yml` workflow uploads reviewed GitHub release assets via
PyPI Trusted Publishing; it never runs automatically on push or release.

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

This section records the checks before publication. The completed publication
is recorded below.

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

## PyPI Trusted Publishing

Create a PyPI account, verify its email and configure two-factor authentication.
For a first publication, add a pending publisher at
<https://pypi.org/manage/account/publishing/> with these exact fields:

- PyPI project: `golded-ftn`
- GitHub owner: `golded-dev`
- GitHub repository: `golded-ftn-python`
- Workflow filename: `publish.yml`
- Environment: `pypi`

See [PyPI's pending-publisher instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
No API token or password is required by the workflow. The account setup is a
manual prerequisite; a GitHub release does not create the PyPI project.

After this tag's CI succeeds and the GitHub release contains both archives and
`RELEASE-SHA256.txt`, run:

```sh
gh workflow run publish.yml --repo golded-dev/golded-ftn-python -f tag=v1.2.2
```

The workflow verifies SHA-256 and uploads those exact release assets. Publish
core first, verify installation from PyPI, then dispatch the format workflows.
Confirm the workflow result, PyPI version and hashes, and installation in a fresh
environment. Do not store publishing credentials in this repository.

## Published 1.2.0 — 2026-10-05

[PyPI](https://pypi.org/project/golded-ftn/1.2.0/) and
[GitHub](https://github.com/golded-dev/golded-ftn-python/releases/tag/v1.2.0)
now provide the reviewed wheel and sdist. The
[publishing workflow](https://github.com/golded-dev/golded-ftn-python/actions/runs/37303913149)
passed with Trusted Publishing through `publish.yml`, environment `pypi`.
The pending publisher became an active project publisher.

Both archives were downloaded from PyPI and their SHA-256 values matched
`RELEASE-SHA256.txt`. A fresh environment installed all five packages at 1.2.0
from `https://pypi.org/simple`, passed `uv pip check`, and executed the four
format CRUD examples. GoldED interoperability remains deferred.

The tagged archives retain the pre-publication documentation used during their
review. Current GitHub documentation records publication; the release tag,
archives and checksum manifest remain unchanged.

## 1.2.1 release — 2026-10-05

Patch release for opt-in mojibake repair. Literal degree signs are protected
while DOS and UTF-8-as-Latin-1 damage elsewhere on the line remains repairable.
Public signatures and runtime dependencies are unchanged.

Run the complete CI gate and distribution verifier for this version. Publish
the reviewed wheel and sdist through the existing Trusted Publishing workflow,
then verify their public hashes and a fresh PyPI installation.

Local checks on macOS with CPython 3.14.6 passed: 130 tests, Ruff lint and
format, strict mypy, public API stubtest, wheel/sdist metadata and contents,
sdist rebuild, isolated installed-wheel tests and consumer typing. CI results
and publication must be verified for the release commit separately.


## Published 1.2.1 — 2026-10-05

[PyPI](https://pypi.org/project/golded-ftn/1.2.1/) and
[GitHub](https://github.com/golded-dev/golded-ftn-python/releases/tag/v1.2.1)
provide the reviewed wheel and sdist from commit `6877fdb`.
[CI](https://github.com/golded-dev/golded-ftn-python/actions/runs/37355096596)
passed on Linux Python 3.12–3.14 and macOS/Windows Python 3.14.
[Trusted Publishing](https://github.com/golded-dev/golded-ftn-python/actions/runs/37355276053)
passed. Both public archives matched the SHA-256 manifest. A fresh environment
installed 1.2.1 from PyPI after refreshing index metadata and passed the
degree-preservation and mixed-mojibake examples.

The archives retain the documentation reviewed before publication. This
publication record does not change the tag, artifacts or checksums.

## Prepared 1.2.2 — 2026-10-06

Patch release for conservative opt-in mojibake repair and historical GoldED+
charset declarations. Add CP866, KOI8-R, CP1251, KOI8-U and CP1125 names while
preserving CP850 defaults. Public signatures and runtime dependencies are unchanged.
Cyrillic heuristic repair evaluation is deferred; decoding support does not
claim Cyrillic repair support. The PHP sibling additionally fixes CP437/CP1125
decoding where mbstring rejects those names.

Publish only the reviewed 1.2.2 wheel, sdist and checksum manifest after the
release version and publication are authorized. Remote CI, tag creation,
GitHub/PyPI publication and public installation are separate checks. The
shared documentation must pin the released core commit before its deployment.

Local macOS checks with CPython 3.14.6 passed: 188 tests, Ruff lint and
format, strict mypy, public API stubtest and locked dependency synchronization.
The distribution gate checks metadata and contents, rebuilds the sdist, then
runs installed-wheel tests and consumer typing outside the checkout. SHA-256
values in `RELEASE-SHA256.txt` identify the final local candidate archives.
Local verification does not establish remote CI or publication.
