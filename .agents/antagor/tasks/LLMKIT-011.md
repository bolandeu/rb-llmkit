---
id: LLMKIT-011
title: The rest of the gateway surface wrapped, documents rewritten and the specification
  and plan sorted
status: queue
attempts: 2
blocked: false
blocked_reason: null
phase: green
tests_hash: 859586cd55093a6731dccf70edae010f17573bc4f0a5daf547de87b83d6d424b
publish_stage: null
created_by: architect
approved_by: human
approved_words: Tvrdí
worker: pi
type: feature
owns_paths:
- src/llmkit/usage.py
test_paths:
- tests/test_media.py
- tests/test_api_surface.py
- tests/test_describe.py
- tests/test_doctor.py
- tests/test_help.py
- tests/test_cost.py
- tests/conftest.py
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
translation: 'Обернуть остальную поверхность шлюза: картинки, речь, видео, embeddings,
  поиск, fetch, модели, responses/messages/systemone/Gemini — по команде на семейство,
  с --json и Example. Документы под новую форму: README, глоссарий, архитектура, карта
  решений; спецификация и план разбираются по разделам — живой документ, ADR, идея
  или выброс (текст и причина на решение Человека).'
---

## What must work

The rest of the gateway surface is wrapped, and the documents match the design that is left.

### The rest of the gateway surface

One typed wrapper and one CLI command group per family, each with --json and a --help that has an Example line:

- images: generation;
- audio: speech, transcriptions, voices;
- video: generation, edits, extensions, get by id;
- embeddings;
- search and web fetch;
- models: list, info, show one;
- the other chat shapes: responses, responses compact, messages, messages count tokens, systemone, and the Gemini-shaped models endpoint.

A media answer is a file or a URL, not a parse of a provider format; llmkit keeps no provider list and no keys of its own.

### The documents

- README is the reader's path: what llmkit is now (an overlay over 9router), the requirement of a running gateway, install, routing example with one gateway provider and the gateway key variable, one example per command group, and how an agent drives the CLI (--help, --json, exit codes). Every command and flag it shows exists and matches --help.
- The glossary keeps only terms of the current design: no journal, response cache, tags, budget, cost source, transports or price table of llmkit.
- The architecture document describes the modules as they are now; no database layer, no migrations, no subscription transports, no serve.
- The decision map names who decides what, with the gateway as the only access, no own state and the doc kinds.
- The v1 specification and the plan are sorted section by section into a living document, an ADR, a research record, an idea, or the drop list; both files are deleted only when every section is accounted for.
- Pointers to the deleted documents are updated in the agent regulation, the README and the architecture document.

## The report

- Every section of the v1 specification and of the plan → its destination: a living document, an ADR, a research record, an idea (with the ready antagor idea add command), or the drop list.
- The drop list carries each dropped section's text verbatim and the reason; the Human decides on it at acceptance, nothing is deleted silently.
- The result of antagor layout check and antagor memory-check as the last lines of the report.
- The list of the commands the README shows, so the Human can run them once.

## Acceptance

- Given a fake gateway answering an image generation, When lm image --json runs, Then the result carries the URL or the written file path, the model and the cost when present, exit 0 [check: tests/test_media.py]
- Given a fake gateway answering speech, When the audio command runs with an output file, Then the bytes are written there and the path is in --json [check: tests/test_media.py]
- Given the embeddings, search, fetch, models and other chat shapes, When each command runs against the fake gateway, Then it returns its typed result and has its own --help with an Example line [check: tests/test_api_surface.py]
- Given lm describe --json after the new commands, When it is regenerated, Then its command tree matches the snapshots and lists every new group [check: tests/test_describe.py]
- Given lm doctor --json, When the gateway answers, Then healthy is true and the checks name the gateway; when it does not answer, healthy is false [check: tests/test_doctor.py]
- Given the README, When each command and flag it shows is compared with --help, Then every one exists with that flag [check: tests/test_help.py]
- Given the glossary and the architecture document, When they are searched for the removed words, Then no term describes the response cache, the journal, tags, budgets, cost source, the subscription transports or the price table [check: tests/test_help.py]

## How to test

Unit, no network: the httpx gateway stub of the first task returns recorded answers of every family (image, speech, video, embeddings, search, fetch, models, responses, messages, systemone, Gemini-shaped models). Documents: the Human reads the report and runs the README commands once against the fake gateway or a real one.

## Basis

Reuse the gateway client and the error kinds of the first task and the guard/emit CLI pattern; follow docs/cli-conventions.md, ADR-0001 and the doc kinds of the antagor-method skill.

## Read first

- `docs/adr/0001-nadstroyka-nad-9router.md` — the whole surface and what stays
- `README.md` — the reader's path that is being rewritten
- `docs/prd.md` — the specification that is sorted
- `docs/backlog.md` — the plan that is sorted
- `docs/decisions.md` — who decides what

## Out of scope

- Moving other repositories to the new API or to the gateway journal.
- Publishing a release of its own; the epic closes it.

## Feedback

### Blocked: aborted

Parked on purpose while LLMKIT-010 fixes the cost period blocker (its help text and snapshots change). Back in queue: the overlap with LLMKIT-010 keeps you from starting until it finishes, and you will stack on its branch, which already carries that fix. The prd.md and backlog.md sorting stays yours, as the review of LLMKIT-010 said.

### Attempt 1: out of the task's bounds (the changes were reverted)

- `AGENTS.md`
- `CONTEXT.md`
- `README.md`
- `docs/architecture.md`
- `docs/backlog.md`
- `docs/decisions.md`
- `docs/prd.md`

### Answer to question #4

> Red phase writes only test_paths (attempt 1 was reverted for docs edits), but `antagor submit` refuses until all seven docs of the task change; both blockers are mechanical, so this round cannot submit. Inbox note 3 also puts tests/test_cost.py (not in test_paths) in my test work.
> Question: How do I end this red round: which boundary changes first?
> Options:
> 1. Set docs to none for the red phase (restore the seven at green) and add tests/test_cost.py to test_paths
> 2. Widen the red scope with the seven docs files, so I touch them now and sort them at green
> 3. Start LLMKIT-011 at green now: the red commit 35e04ba is in, and green writes code and docs
> Recommended: Set docs to none for the red phase (restore the seven at green) and add tests/test_cost.py to test_paths

Both blockers are mine to remove, not yours to fight. 1) The docs promise is dropped for the red phase: AGENTS.md, CONTEXT.md, README.md, docs/architecture.md, docs/decisions.md, docs/prd.md, docs/backlog.md are written in green (they are in your owns), and I put the promise back before your green submit so the gate still holds you to it. 2) tests/test_cost.py joined your test_paths: the regression test for the cost period (finding #3) belongs to the red phase, frozen in green afterwards. Red: test files only. Green: code, CLI, docs.

### Blocked: needs_scope (entries [{'n': 4, 'text': 'Red phase writes only test_paths (attempt 1 was reverted for docs edits), but `antagor submit` refuses until all seven docs of the task change; both blockers are mechanical, so this round cannot submi'}])

Both blockers removed by the Architect: the docs promise is off for the red phase (docs are written in green; I put the seven files back before your green submit), and tests/test_cost.py joined your test_paths — write the cost-period regression test in red (finding #3). Red: test files only. Green: code, CLI and all documents of your owns.

### Attempt 2: the Architect's verdict

The review found blockers; close each:

- [blocker] [wrong] The cost-period contract frozen at green is broken at this HEAD: `tests/test_cost.py::test_iso_timestamp_bounds_cut_inside_a_day` fails (`--since 2026-11-01T06:00:00Z` → exit 2, `INVALID_ARGUMENTS: "не понимаю период"`). The green commit `8323f02` fixed `src/llmkit/usage.py::​_moment` (`datetime.fromisoformat`) and `_bound`; the merge commit `9adde31` took the LLMKIT-010 side (`strptime %Y-%m-%d`, date-only) and reverted it, keeping 011's test. Current full run: 1 failed, 728 passed — the report's "726 passed, all five checks green" describes the pre-merge tree, not the submitted HEAD. Fix: restore the green `usage.py` (`fromisoformat` + `_bound` end bound); note that `src/llmkit/usage.py` is outside this task's owned paths (`src/llmkit/gateway/`, `src/llmkit/cli/`, `tests/`, `docs/`, `doctor.py`) — the Architect must put it into scope or move the fix to a follow-up before acceptance. — «`tests/test_cost.py` joined your test_paths: the regression test for the cost period (finding #3)… frozen in green afterwards»

Minor remarks of the review: optional, if they do not widen the task:

- [minor] [missing] The layout check and memory-check results are near the end of the report but not the last lines: a status line ("`On the main checkout now: 2 docs to sort`") follows them. — «The result of antagor layout check and antagor memory-check as the last lines of the report»
- [minor] [missing] The three `antagor idea add` commands in the report carry `--text "..."` placeholders, so they are not ready to run; the real texts live in `.agents/antagor/ideas/LLMKIT-IDEA-00{5,6,7}.md` (I checked: the files exist in the main checkout). — «an idea (with the ready antagor idea add command)»

### Blocked: aborted

src/llmkit/usage.py is in your owns now. The blocker: the merge with LLMKIT-010 took 010's date-only parser and dropped your ISO-timestamp support, so tests/test_cost.py::test_iso_timestamp_bounds_cut_inside_a_day fails at HEAD (--since 2026-11-01T06:00:00Z exits 2). Re-apply _moment/_bound on top of 010's version: date-only and full ISO with Z both parse, the day range stays correct. The rest of the round stands — do not redo the documents.
