---
id: LLMKIT-013
title: 'AGENTS.md: the ladder for a plan defect found mid-run'
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
type: docs
owns_paths:
- AGENTS.md
test_paths:
- tests/conftest.py
docs:
- AGENTS.md
tools: []
worker_args: null
class: mechanical
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks: manual
resident: null
tool: null
pr: null
---

Carried over from LLMKIT-011 inbox finding #1 (the section was written, then reverted by the ownership guard while AGENTS.md belonged to LLMKIT-011). Add a Russian section «Дефект плана нашёлся на ходу» before «Версии, changelog, справка», three levels from cheap to expensive. Level 1 — a project setting in .agents/antagor/antagor.toml (checks, limits, protocol): Antagor reads the config again each round, so fix it and unblock the task with a note; the protocol test command carries the no-coverage flag because Antagor appends the task's test paths and the coverage gate then fails a subset with every test green (6.11: three attempts burned), while coverage is judged by the full pytest run in checks. Level 2 — the task card: task-update changes boundaries, description and dependencies, then unblock with a note; a worker question is answered with the inbox resolve command. Level 3 — code and tests in the task branch are written only by the worker: a test path is frozen in the green phase, its edits are reverted and the attempt is spent, the reverted work stays as a patch under the kept directory; one-off, on the Human's words, the path goes into the architect zone, the Architect commits and the block is removed at once (6.11: a frozen gateway client test); rework is asked only when the assertions themselves are wrong, then the red phase is fixed rather than the text.

## Acceptance

- Given AGENTS.md, When the Architect reads it before fixing a plan defect mid-run, Then the three levels and their commands are there, each with the live example from 6.11 [check: manual]

## How to test

Read AGENTS.md: the section sits before «Версии, changelog, справка», the commands are copy-pasteable, no dynamic state (release dates, statuses, branches).

## Basis

The wording is the Architect's note in the inbox (LLMKIT-011 #1); the style follows the rest of AGENTS.md (Russian, short, imperative).

## Read first

- `AGENTS.md`
- `.agents/antagor/antagor.toml`

## Out of scope

- Any change outside AGENTS.md
