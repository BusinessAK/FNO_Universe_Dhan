AGENTS — Agent Instructions for this Repository

Purpose
- Provide brief, actionable guidance for AI coding agents working in this repository. Link to project docs rather than duplicating them.

Quick Commands
- **Install deps:** `python3 -m pip install -r requirements.txt` ([requirements.txt](requirements.txt))
- **Run tests:** `python3 run_tests.py` ([run_tests.py](run_tests.py))
- **Start demos/pipelines:** `./start.sh <mode>` — common modes: `eod`, `live`, `dash` ([start.sh](start.sh#L1-L40))

Important Files & Directories
- **Entry scripts:** [daily_compiler.py](daily_compiler.py#L1-L40), [main.py](main.py#L1-L40), [dashboard.py](dashboard.py)
- **Core code:** [vanguard/](vanguard/) — engines, data fetchers, ML, services
- **Compiled data:** [data/compiled/](data/compiled/) and `vanguard.duckdb` (authoritative compiled dataset)
- **Processed intermediates:** [data/processed/](data/processed/)
- **Models:** [data/models/](data/models/)
- **Docs:** [docs/compiler_contract.md](docs/compiler_contract.md) and [instructions.md](instructions.md)

Agent Rules & Conventions (short)
- **Link, don't embed:** prefer linking to existing docs in `docs/` and root files.
- **Do not perform live downloads in CI:** avoid running scripts that hit external APIs unless `SKIP_LIVE_TESTS` is unset and the user approved — prefer mocks or recorded data in `data/raw/`.
- **Do not overwrite `data/compiled/` without consent:** use `data/processed/` or create a temp workspace; use `--force` only when explicitly requested.
- **Tests:** run `python3 run_tests.py` and local failing tests only; use `SKIP_LIVE_TESTS=1` to skip network tests.
- **Code changes:** keep edits minimal, run targeted unit tests, and prefer updating existing tests or adding new tests under `tests/`.

When editing or adding agents
- Prefer `AGENTS.md` at repo root (this file) over `.github/copilot-instructions.md` for repo-scoped agent guidance.
- For specialized guidance (tests, data-management, ML), create small skill files under `.github/agents/` or separate AGENTS-*.md files and link them here.

Next suggested agent customizations
- `AGENTS-tests.md`: test-runner conventions and common flakiness mitigations.
- `AGENTS-data.md`: safe data handling, canonical locations, and how to create reproducible fixtures.

If you want, I can add the first of those (tests or data) next.
