---
id: LLMKIT-008
title: 'Documents of the gateway design: README, glossary, architecture, and the sorting
  of the specification and the plan'
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
- README.md
- CONTEXT.md
- AGENTS.md
- CODING_STANDARDS.md
- docs/
test_paths:
- tests/test_describe.py
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
class: standard
decision: false
visual: null
depends_on:
- LLMKIT-006
- LLMKIT-007
budget_usd: null
epic: E-002
spec_refs: []
checks: manual
resident: null
tool: null
pr: null
translation: 'Документы под шлюзовую архитектуру: README, глоссарий, архитектура,
  карта решений; спецификация и план разбираются по разделам — живой документ, ADR,
  идея или выброс (выбросы — с текстом и причиной, решает Человек). Оба файла удаляются.'
---

## What must work

The documents describe the product as it is after the gateway rework, and no loose document stays.

- README is the reader's path: what llmkit is now (an overlay over 9router), the requirement of a running gateway, install, routing example with one gateway provider and the gateway key variable, one example per command group (ask, generate, ask_many, decide, image, audio, video, embeddings, search, fetch, models, cost, doctor, describe), and how an agent drives the CLI (--help, --json, exit codes). Every command and flag it shows exists and matches --help.
- The glossary keeps only terms of the current design: no journal, response cache, tags, budget, cost source, transports or price table of llmkit.
- The architecture document describes the modules as they are now: the gateway client, the wrappers, the CLI, the contracts; no database layer, no migrations, no subscription transports, no serve.
- The decision map names who decides what, with the gateway as the only access, no own state, and the doc kinds.
- The v1 specification and the plan are sorted, section by section: each goes to a living document, an ADR, a research record, an idea (antagor idea add --text …) or the drop list. Nothing is lost silently: the drop list carries the text verbatim and the reason, and the Human decides on it at acceptance. Both files are deleted only when every one of their sections is accounted for.
- Ideas that the plan puts off are created one per item, with the source section in the text.
- Pointers to the deleted documents are updated everywhere: the agent regulation, the README, the architecture document.

## Acceptance

- Given the repository, When antagor layout check runs, Then no document is left to sort and the layout reports no gap (check: manual) [check: manual]
- Given every section of the v1 specification and of the plan, When the report is read, Then each one names its destination, and the proposed drops are listed with their text verbatim and the reason (check: manual) [check: manual]
- Given the README, When a reader follows it from install to every example, Then each command and flag in it exists and matches what its --help prints (check: manual) [check: manual]
- Given the agent regulation, When antagor memory-check runs, Then it reports nothing to fix (check: manual) [check: manual]
- Given the glossary, When it is read, Then no term describes removed code: no journal, response cache, tags, budget, transports or price table of llmkit (check: manual) [check: manual]

## How to test

Manual: the Human reads the report and the README; the commands quoted in the README are run once against the fake gateway or a real one.

## Basis

Follow the doc kinds of the antagor-method skill; reuse ADR-0001, ADR-0002, ADR-0003 and docs/decisions.md as the source of the decisions.

## Read first

- `docs/adr/0001-nadstroyka-nad-9router.md`
- `docs/decisions.md`
- `README.md`
- `docs/prd.md`
- `docs/backlog.md`

## Out of scope

- Code and tests; moving other repositories.
- Publishing a release of its own; the epic closes it.
