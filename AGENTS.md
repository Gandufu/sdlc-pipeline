# Repository Guidelines

## Project Structure & Module Organization

This repository delivers an OpenCode-first, deterministic SDLC pipeline. The thin JavaScript host adapter is in `.opencode/plugins/sdlc-pipeline.js`; commands, agents, and skills live beside it under `.opencode/`. Python business logic and state-machine checks belong in `scripts/sdlc_core/`; `scripts/sdlc.py` is the CLI entry point. JSON Schemas are in `schemas/`, runtime templates in `templates/`, and reusable policy/reference material in `rules/` and `references/`. Keep architecture decisions in `docs/adr/` and design details in `docs/design/`. Python regression suites live in `tests/`.

## Build, Test, and Development Commands

Run these from the repository root on Windows:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -X utf8 -m unittest discover -s tests -v  # Python regression suite
node --check .opencode/plugins/sdlc-pipeline.js # adapter syntax check
git diff --check                                # whitespace/errors in the diff
```

Use `python scripts/install_project.py --target <isolated-project>` to validate installation. Do not install dependencies or modify the fixed source checkout when performing an audit; use a separate target project and sibling evidence directory.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, `pathlib.Path`, and `snake_case` in Python. Keep Python Core deterministic and host-independent; do not move state-machine decisions into OpenCode hooks. JavaScript uses two spaces, ESM imports, `camelCase` functions, and early returns. Name tests `test_*.py`, classes `*Tests`, schema files `*.schema.json`, and ADRs `NNNN-kebab-case.md`. Prefer small, focused changes; never duplicate long source content into JSON indexes.

## Testing Guidelines

Add or update a regression test for every behavior change. Keep fixtures isolated and clean them up in `tearDown`. Run the focused test file during development, then the full suite and both static checks before handoff. Browser or functional checks belong only after the target project has started and passed readiness.

## Commit & Pull Request Guidelines

Use conventional, lowercase subjects such as `feat: adopt storage layout v3`, `fix: normalize file source path aliases`, or `refactor: remove generic release smoke`. Keep commits scoped. PRs should explain the behavior change, affected contracts/schemas, validation commands and results, and any approval or migration impact; include screenshots only for UI-visible changes.

## Agent-Specific Instructions

For unfamiliar technology, external services, schema/architecture choices, production dependencies, migrations, or security-sensitive work: inspect first, separate confirmed facts from assumptions, present options and a recommendation, and wait for explicit implementation approval. “Adopt recommendation” is not release approval; commits, pushes, and publication require separate confirmation.
