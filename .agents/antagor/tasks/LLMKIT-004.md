---
id: LLMKIT-004
title: 'Cache surfaces: config path, describe, doctor, docs'
status: ideas
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: null
worker: claude-code
type: feature
owns_paths:
- src/llmkit/cli
- src/llmkit/data_files.py
- src/llmkit/doctor.py
- docs/prd.md
- README.md
test_paths:
- tests/test_cli.py
- tests/test_describe.py
- tests/test_doctor.py
- tests/test_config.py
docs:
- docs/prd.md
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
translation: 'Все места, где сказано, где кэш: config path/show, describe, doctor,
  PRD — теперь это БД.'
---

Everything that tells where the cache is says it is the database now: llm config path/show, llm describe (x-rb-data), llm doctor, the PRD section 7 and the default table.

## Acceptance

- Given LLMKIT_DATABASE_URL is set, When 'llm config path --json' runs, Then the cache location is that database (url without password) [check: tests/test_cli.py]
- Given no URL, When 'llm config show' runs, Then the cache is reported in the local default database [check: tests/test_config.py]
- Given 'llm describe --json', When read, Then llmkit_cache is listed as kind cache and cache.sqlite is not listed as the cache store [check: tests/test_describe.py]
- Given the database is unreachable, When 'llm doctor' runs, Then the cache line reports the database error, not a file path [check: tests/test_doctor.py]

## How to test

Unit through the CLI runner with --json; no real PostgreSQL.

## Basis

Follow the existing config path and describe code.

## Out of scope

- Storage code and migration.
