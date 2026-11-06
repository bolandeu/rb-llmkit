---
id: LLMKIT-010
title: 'Nothing of its own left: state and transports out, the whole gateway surface
  wrapped, documents rewritten'
status: ideas
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: null
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
- src/llmkit/cli/
- src/llmkit/gateway/
- pyproject.toml
- uv.lock
- scripts/pg_test.sh
- .gitea/workflows/ci.yml
- tests/
- README.md
- CONTEXT.md
- AGENTS.md
- CODING_STANDARDS.md
- docs/
- src/llmkit/__init__.py
- src/llmkit/errors.py
test_paths:
- tests/test_cost.py
- tests/test_media.py
- tests/test_api_surface.py
- tests/test_help.py
- tests/test_describe.py
- tests/test_deps.py
- tests/test_usage.py
- tests/test_keys.py
- tests/test_health.py
docs:
- README.md
- CONTEXT.md
- AGENTS.md
- CODING_STANDARDS.md
- docs/architecture.md
- docs/decisions.md
- docs/prd.md
- docs/backlog.md
tools: []
worker_args: null
class: hard
decision: false
visual: null
depends_on:
- LLMKIT-009
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

llmkit keeps nothing of its own and wraps the whole gateway surface.

### Own state, gone

- No database layer, no tables, no views, no migrations, no LLMKIT_DATABASE_URL, no db command group.
- No journal writes from the call path and no response cache at all: no cache file, no cache table, no --no-cache flag, no cache_hit field, no cache status.
- Spend is read from the gateway journal, read-only: the gateway SQLite (usageHistory and usageDaily), never written, never migrated. A consumer is told apart by its gateway API key.
- The last existing command keeps working as it does now: lm cost --json reports spend for a period, grouped by the gateway API key, from the gateway journal; a missing or unreadable gateway database is a clear error with the existing unavailable exit code and a hint naming the path.

### Own access, gone

- The subscription transports and the login of subscriptions are removed: the subscriptions live in the gateway.
- lm serve and its extra dependency are removed.
- Keys: llmkit resolves only the name of the gateway key variable; keyring and provider key lookups are removed. lm auth status --json reports the gateway key.
- Dependencies are pruned in the same change and the lock is regenerated: LiteLLM, Instructor, SQLAlchemy, Alembic, psycopg, keyring, and the proxy extra are absent from the installed package.

### The rest of the gateway surface, wrapped

One typed wrapper and one CLI command group per family, each with --json and a --help that has an Example line:

- images: generation;
- audio: speech, transcriptions, voices;
- video: generation, edits, extensions, get by id;
- embeddings;
- search and web fetch;
- models: list, info, show one;
- the other chat shapes: responses, responses compact, messages, messages count tokens, systemone, and the Gemini-shaped models endpoint.

A media answer is a file or a URL, not a parse of a provider format; llmkit keeps no provider list and no keys of its own.

### Contracts

- lm describe --json lists the new command tree and only the data files that still exist.
- lm doctor --json checks the gateway (as the first task set) and no database.

## What must work

The documents describe the product as it is after the gateway rework, and no loose document stays.

- README is the reader's path: what llmkit is now (an overlay over 9router), the requirement of a running gateway, install, routing example with one gateway provider and the gateway key variable, one example per command group (ask, generate, ask_many, decide, image, audio, video, embeddings, search, fetch, models, cost, doctor, describe), and how an agent drives the CLI (--help, --json, exit codes). Every command and flag it shows exists and matches --help.
- The glossary keeps only terms of the current design: no journal, response cache, tags, budget, cost source, transports or price table of llmkit.
- The architecture document describes the modules as they are now: the gateway client, the wrappers, the CLI, the contracts; no database layer, no migrations, no subscription transports, no serve.
- The decision map names who decides what, with the gateway as the only access, no own state, and the doc kinds.
- The v1 specification and the plan are sorted, section by section: each goes to a living document, an ADR, a research record, an idea (antagor idea add --text …) or the drop list. Nothing is lost silently: the drop list carries the text verbatim and the reason, and the Human decides on it at acceptance. Both files are deleted only when every one of their sections is accounted for.
- Ideas that the plan puts off are created one per item, with the source section in the text.
- Pointers to the deleted documents are updated everywhere: the agent regulation, the README, the architecture document.

## The report

- Every section of the v1 specification and of the plan → its destination: a living document, an ADR, a research record, an idea (with the ready `antagor idea add --text "…"` command), or the drop list.
- The drop list carries each dropped section's text verbatim and the reason; the Human decides on it at acceptance, nothing is deleted silently.
- The result of `antagor layout check` and `antagor memory-check` as the last lines of the report.
- The list of the commands the README shows, so the Human can run them once.

## Acceptance

- Given the CLI root help, When it is printed, Then the db group, the subscription login, serve and the old config-db command are absent and every remaining command lists --json [check: tests/test_help.py]
- Given a gateway SQLite with usageHistory and usageDaily rows, When lm cost --json --since 1d runs, Then spend is grouped by the gateway API key and the file was opened read-only (no write, mtime unchanged) [check: tests/test_cost.py]
- Given no gateway database, When lm cost --json runs, Then it exits with the existing unavailable code and a hint naming the gateway path [check: tests/test_cost.py]
- Given a completed ask, When the process ends, Then no journal row and no cache row exist anywhere and the --json answer has no cache_hit field [check: tests/test_usage.py]
- Given the installed package, When its metadata and the lock are read, Then litellm, instructor, sqlalchemy, alembic, psycopg, keyring, fastapi and uvicorn are absent and uv lock --check passes [check: tests/test_deps.py]
- Given a fake gateway answering an image generation, When lm image --json runs, Then the result carries the URL or the written file path, the model and the cost when present, exit 0 [check: tests/test_media.py]
- Given a fake gateway answering speech, When the audio command runs with an output file, Then the bytes are written there and the path is in --json [check: tests/test_media.py]
- Given the embeddings, search, fetch, models and other chat shapes, When each command runs against the fake gateway, Then it returns its typed result and has its own --help with an Example line [check: tests/test_api_surface.py]
- Given lm describe --json, When it is generated, Then its command tree matches the snapshots and its data files name only paths that still exist [check: tests/test_describe.py]
- Given a missing gateway key variable, When a call runs, Then the key error names the variable and the exit code is unchanged [check: tests/test_keys.py]
- Given lm auth status --json, When it runs, Then it reports the gateway key and no subscription [check: tests/test_health.py]

## How to test

Unit, no network: the httpx gateway stub of the first task returns recorded answers; the gateway journal is a SQLite file the test builds in a temporary folder. The documents: the Human reads the report and runs the README commands once.

## Basis

Reuse the gateway client, the error kinds and EXIT_CODES of the first task, the guard/emit CLI pattern and the isolated fixture; follow docs/cli-conventions.md, ADR-0001 and the doc kinds of the antagor-method skill.

## Read first

- `docs/adr/0001-nadstroyka-nad-9router.md`
- `src/llmkit/cli/main.py`
- `src/llmkit/opencli.py`
- `docs/prd.md`
- `docs/backlog.md`

## Out of scope

- Moving other repositories to the new API or to the gateway journal; publishing a release of its own (the epic closes it).
