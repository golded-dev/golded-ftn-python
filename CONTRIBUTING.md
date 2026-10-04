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
