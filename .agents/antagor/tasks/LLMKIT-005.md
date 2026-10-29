---
id: LLMKIT-005
title: Two-worker acceptance on PostgreSQL
status: in_review
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
- tests/test_cache_pg.py
- scripts/pg_test.sh
test_paths:
- tests/test_cache_pg.py
docs: none
tools: []
worker_args: null
class: standard
decision: false
visual: null
depends_on:
- LLMKIT-003
budget_usd: null
epic: E-001
spec_refs: []
checks:
- python3 scripts/check_command_docstrings.py
resident: null
tool: null
pr: null
translation: 'Приёмка marketer как тест на PostgreSQL: два воркера, один ответ, второй
  — hit за 0, usage в той же БД.'
---

The marketer's acceptance as a PostgreSQL test: two workers (separate processes) make one call; the second gets the same answer as a hit with cost 0, and usage rows of both are in the same database.

## Acceptance

- Given two processes on one PostgreSQL URL, When both ask the same call at the same time, Then both get the same answer and exactly one cache row exists [check: tests/test_cache_pg.py]
- Given the first answer is stored, When a third process asks the call, Then it is a hit, cost 0, and llmkit_calls holds the status=cache row in the same database [check: tests/test_cache_pg.py]

## How to test

Integration via scripts/pg_test.sh (detached), fake provider, real PostgreSQL.

## Basis

Follow the existing PostgreSQL tests run by pg_test.sh.

## Out of scope

- Storage code.
