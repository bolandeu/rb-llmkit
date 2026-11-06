---
id: LLMKIT-010
title: 'Nothing of its own left: state, transports and their commands out, dependencies
  pruned'
status: in_review
attempts: 2
blocked: false
blocked_reason: null
phase: green
tests_hash: 1b126407241df7a1ebb3486954a4b6f850b6fe7b2e733c7ece62c885b3d7f661
publish_stage: null
created_by: architect
approved_by: human
approved_words: Tvrdí
worker: pi
type: feature
owns_paths:
- src/llmkit/db/
- src/llmkit/cache.py
- src/llmkit/usage.py
- src/llmkit/keys.py
- src/llmkit/transports/
- src/llmkit/data_files.py
- src/llmkit/health.py
- src/llmkit/opencli.py
- src/llmkit/doctor.py
- src/llmkit/legacy.py
- src/llmkit/core.py
- src/llmkit/providers.py
- src/llmkit/__init__.py
- src/llmkit/cli/
- pyproject.toml
- uv.lock
- scripts/pg_test.sh
- .gitea/workflows/ci.yml
- tests/
- AGENTS.md
- CONTEXT.md
- README.md
- docs/architecture.md
- docs/cli-conventions.md
- docs/testing.md
- scripts/detach.py
- scripts/smoke.py
- src/llmkit/_distribution.py
- src/llmkit/callutil.py
- src/llmkit/config.py
- src/llmkit/contracts/routing-v1.schema.json
- src/llmkit/errors.py
- src/llmkit/models.py
- src/llmkit/routing.py
test_paths:
- tests/test_cost.py
- tests/test_usage.py
- tests/test_keys.py
- tests/test_health.py
- tests/test_help.py
- tests/test_describe.py
- tests/test_deps.py
docs: none
tools: []
worker_args: null
class: hard
decision: false
visual: null
depends_on: []
budget_usd: null
epic: E-003
spec_refs: []
checks:
- uv run pytest -q
- uv run ruff check .
- uv run ruff format --check .
- uv run ty check
- python3 scripts/check_command_docstrings.py
resident: null
tool: null
pr: null
translation: 'Убрать своё: слой БД, журнал, кэш, прайс, транспорты подписок, serve,
  keyring и лишние зависимости; расход — из журнала шлюза read-only. Обернуть всю
  остальную поверхность шлюза (картинки, речь, видео, embeddings, поиск, fetch, модели,
  responses/messages/systemone/Gemini). Документы под новую форму: README, глоссарий,
  архитектура; спецификация и план разбираются по разделам — живой документ, ADR,
  идея или выброс с текстом и причиной.'
---

## What must work

llmkit keeps nothing of its own: state, provider access and the commands around them go.

### Own state, gone

- No database layer, no tables, no views, no migrations, no LLMKIT_DATABASE_URL, no db command group.
- No journal writes from the call path and no response cache at all: no cache file, no cache table, no --no-cache flag, no cache_hit field, no cache status.
- Spend is read from the gateway journal, read-only: the gateway SQLite (usageHistory and usageDaily), never written, never migrated. A consumer is told apart by its gateway API key.
- lm cost --json keeps reporting spend for a period, grouped by the gateway API key, from the gateway journal; a missing or unreadable gateway database is a clear error with the existing unavailable exit code and a hint naming the path.

### Own access, gone

- The subscription transports and the login of subscriptions are removed: the subscriptions live in the gateway.
- lm serve and its extra dependency are removed.
- Keys: llmkit resolves only the name of the gateway key variable; keyring and provider key lookups are removed. lm auth status --json reports the gateway key.
- Dependencies are pruned in the same change and the lock is regenerated: LiteLLM, Instructor, SQLAlchemy, Alembic, psycopg, keyring and the proxy extra are absent from the installed package.

### Contracts

- lm describe --json lists the remaining command tree and only the data files that still exist.
- Every remaining command keeps --help with an Example line and --json.

## Acceptance

- Given the CLI root help, When it is printed, Then the db group, the subscription login, serve and the old config-db command are absent and every remaining command lists --json [check: tests/test_help.py]
- Given a gateway SQLite with usageHistory and usageDaily rows, When lm cost --json --since 1d runs, Then spend is grouped by the gateway API key and the file was opened read-only (no write, mtime unchanged) [check: tests/test_cost.py]
- Given no gateway database, When lm cost --json runs, Then it exits with the existing unavailable code and a hint naming the gateway path [check: tests/test_cost.py]
- Given a completed ask, When the process ends, Then no journal row and no cache row exist anywhere and the --json answer has no cache_hit field [check: tests/test_usage.py]
- Given the installed package, When its metadata and the lock are read, Then litellm, instructor, sqlalchemy, alembic, psycopg, keyring, fastapi and uvicorn are absent and uv lock --check passes [check: tests/test_deps.py]
- Given a missing gateway key variable, When a call runs, Then the key error names the variable and the exit code is unchanged [check: tests/test_keys.py]
- Given lm auth status --json, When it runs, Then it reports the gateway key and no subscription [check: tests/test_health.py]
- Given lm describe --json, When it is generated, Then its command tree matches the snapshots and its data files name only paths that still exist [check: tests/test_describe.py]

## How to test

Unit, no network: the httpx gateway stub of the first task returns recorded answers; the gateway journal is a SQLite file the test builds in a temporary folder.

## Basis

Reuse the gateway client, the error kinds and EXIT_CODES of the first task, the guard/emit CLI pattern and the isolated fixture; follow docs/cli-conventions.md and ADR-0001.

## Read first

- `docs/adr/0001-nadstroyka-nad-9router.md` — what stays and what goes
- `src/llmkit/cli/main.py` — the command tree
- `src/llmkit/usage.py` — the journal and cost code that goes
- `src/llmkit/opencli.py` — the describe contract
- `src/llmkit/cli/cost.py` — the command that reads the journal

## Out of scope

- Media and the other non-chat endpoints; documents; moving other repositories to the new API or to the gateway journal.
- Publishing a release of its own; the epic closes it.

## Feedback

### Attempt 1: the Architect's verdict

The review found blockers; close each:

- [blocker] [wrong] `cost` advertises a date format the code rejects: `--since/--until` help, `PERIOD_HINT` and the error message promise «7d, 12h, 2w или ГГГГ-ММ-ДД», but `usage._since` parses only digits+unit and `llm cost --since 2026-11-01` fails with INVALID_ARGUMENTS (checked on this HEAD). Task: «lm cost --json keeps reporting spend for a period» — either parse dates or fix every promise (help, snapshot, describe). Every remaining-command docstring is a checked contract here.

Minor remarks of the review: optional, if they do not widen the task:

- [minor] C11 src/llmkit/cli/app.py: root help still shows `-m ПРОВАЙДЕР/МОДЕЛЬ … можно несколько: -m a/x -m b/y`. ADR-0001: variants with `/` are no longer provider–model; the same file's example uses `-m "Deep Sec"`. Stale example in the same help.
- [minor] C3 src/llmkit/cli/cost.py: totals recomputed row-wise in the command while `usage.total()` does the same; one of them should go.
- [minor] C6 src/llmkit/core.py: `try: … except GatewayUnavailable: raise` is a no-op pass-through, leftover of the removed journaling.
- [minor] C9 src/llmkit/usage.py: `total()` is defined and never used in the tree (the CLI recomputes inline instead).
- [minor] C9 src/llmkit/health.py: `check_key(kind, …)` — `kind` parameter is never read; the caller passes `cfg.protocol` for nothing.
- [minor] usage.py: `with _open(target) as connection` never closes the sqlite3 connection (context manager only manages transactions); harmless per-process but leaks a fd per call.
- [minor] [missing] Task names both journal tables — «the gateway SQLite (usageHistory and usageDaily)» — but usage.py reads only `usageHistory`; `usageDaily` appears only in the test fixture and the journal glossary. Grouping by API key is met without it, so acceptable if the Architect agrees the daily aggregate is unused.
- [minor] [missing] Acceptance «Then spend is grouped by the gateway API key» quoted against `_daily`/`byApiKey`: fixture builds `usageDaily.byApiKey`, but no code path ever reads it (same point as above, list once for decision).
