---
id: LLMKIT-003
title: Cache in the usage database (table, migration 0003, first write wins)
status: done
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: human
approved_words: да
worker: claude-code
type: feature
owns_paths:
- src/llmkit/cache.py
- src/llmkit/core.py
- src/llmkit/db
- src/llmkit/config.py
test_paths:
- tests/test_cache.py
- tests/test_core.py
- tests/test_db.py
- tests/snapshots/describe.json
docs: none
tools: []
worker_args: null
class: standard
decision: false
visual: null
depends_on: []
budget_usd: null
epic: E-001
spec_refs: []
checks:
- python3 scripts/check_command_docstrings.py
resident: null
tool: null
pr: null
translation: 'Кэш в БД учёта: таблица llmkit_cache, миграция 0003, первая запись побеждает,
  сбой БД не валит вызов.'
---

The response cache lives in the same database as usage (PostgreSQL from LLMKIT_DATABASE_URL, else the local SQLite). Workers on one URL share it: the second identical call is a free hit with the first one's answer. A write never replaces an existing entry. A database failure on the cache never fails a call.

## Acceptance

- Given two LlmKit instances on one database URL, When the first asks a call and the second the same call, Then the second is source=cache with the first answer and cost 0 [check: tests/test_cache.py]
- Given two writers of one key, When both set it, Then the first value stays and later get returns it [check: tests/test_cache.py]
- Given a database at 0002, When migration 0003 runs, Then llmkit_cache exists, status shows head 0003, llmkit_calls rows are unchanged, and metadata matches the migrations (kind cache) [check: tests/test_db.py]
- Given an entry older than ttl_days, When it is asked, Then it is a miss and expired rows are deleted [check: tests/test_cache.py]
- Given no LLMKIT_DATABASE_URL and an old cache.sqlite, When a call is made, Then the local default database serves the cache and the old file is ignored without an error [check: tests/test_cache.py]
- Given the cache database fails on get or set, When a call is made, Then the call goes to the provider and a warning is in Answer.warnings; it does not raise [check: tests/test_core.py]

## How to test

Unit: two LlmKit on one SQLite file via the public ask with a fake provider.

## Basis

Follow Usage in usage.py for the engine and lock; keep make_key unchanged.

## Read first

- `src/llmkit/usage.py`
- `src/llmkit/db/__init__.py`
- `src/llmkit/db/tables.py`

## Out of scope

- Copying old cache.sqlite entries; changing the cache key; CLI and describe text; the PostgreSQL run (other tasks).
