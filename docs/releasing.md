# Release checks

The authoritative version is in `pyproject.toml`. Build metadata follows the
[PyPA guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
No publication has occurred. CI contains no publish job.

Run the contributing checks, then `uv build` and `uv run twine check dist/*`.
Inspect wheel/sdist metadata and contents. Extract the sdist into a temporary
folder and rebuild with `uv build --wheel`. Install that wheel without runtime
dependencies in a clean environment outside the checkout. Run the tests and
README examples against the installed package, and strict mypy on a consumer.

CI covers Linux Python 3.12–3.14 with lint, format, typing and tests; Windows and
macOS run tests on 3.14. CI configuration is not evidence those jobs passed.
Record exact local interpreters and platforms in the handoff.

Before public release, choose the repository and package-index destination and
configure private security reporting. Review the generated AGENTS.md for public
suitability. Tags, remote creation and publication need explicit authorization.
