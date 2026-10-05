# Contributing

Use Python 3.12+ and uv. Run `uv sync --locked`, then:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Keep source bytes distinct from decoded and repaired text. Add focused tests at
the public boundary. Use synthetic fixtures, never private archive messages.
Keep concrete format implementations in consuming packages.

For agent instructions, edit `.agent-fragments/project.md` or
`agent-compose.toml`, then run agent-compose preview, build and check.

When public exports, signatures or fields change, update [the API reference](docs/api.md).
Check every `golded_ftn.__all__` export and all dataclass types/defaults. Keep
standalone Python examples runnable and Ruff-formatted. In the sibling
`golded-ftn-python-docs` checkout, rebuild the reading copy with
`uv run python scripts/build_api_guide.py --sync`, install current wheels with
`uv run python scripts/install_readers.py --local`, and run pytest plus
`scripts/check_examples.py`. These checks validate generated HTML, export
headings, links, example execution and strict typing.
