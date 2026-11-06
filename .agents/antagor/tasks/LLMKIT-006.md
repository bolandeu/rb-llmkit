---
id: LLMKIT-006
title: 'Sort docs/prd.md: every section to a living doc, an ADR, a research record
  or an idea'
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
- docs/prd.md
- docs/architecture.md
- CONTEXT.md
- README.md
- docs/adr/
- docs/research/
- AGENTS.md
- docs/cli-conventions.md
- docs/testing.md
test_paths: []
docs:
- docs/prd.md
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: E-002
spec_refs: []
checks: manual
resident: null
tool: null
pr: null
translation: 'Разобрать docs/prd.md по видам: раздел → живой документ, ADR, запись
  исследования, идея; что устарело — предложить к выбросу. Файл удаляется в конце,
  отчёт — таблицей.'
---

## What this task is

`docs/prd.md` is the v1 specification (13 sections, ~370 lines). A specification is not one of the four doc kinds, so the file is sorted and deleted. Its content is not dropped silently: every section goes to a living doc, an ADR, a research record, an idea, or stays as a proposed drop for the Human.

## Rules

1. Walk the file section by section (## 1 … ## 13, including the tables and code blocks).
2. For each section decide one destination and write it into the file it goes to:
   - a **living doc**: `README.md` (user-facing usage, install, keys), `CONTEXT.md` (terms), `docs/architecture.md` (module map, lazy imports, DB layer, routing, CLI contract), `docs/cli-conventions.md`, `docs/testing.md`;
   - a **new ADR** `docs/adr/NNNN-slug.md` (next free number after 0003) — only for a decision that is hard to undo, would surprise a reader without context, and was a real choice. ADR-0001 (9router layer), ADR-0002 (routing as data), ADR-0003 (one journal database) already exist: do not duplicate them, supersede them if the spec says otherwise;
   - a **research record** `docs/research/YYYY-MM-DD-slug.md` — only for a dated experiment with numbers (the `docs/smoke-2026-09.md` reference in §12 is such a record: restore it only if its data exists in git history, otherwise say in the report that it is lost);
   - an **idea**: `antagor idea add --text "…"` for pending work, one idea per item, with the spec section in the text. No `--for`: the list of this project;
   - a **drop**: leave the section in place, list it in the report with the reason; never delete a dropped section — the Human decides at acceptance.
3. Where the spec is already overtaken, say so and use the code as truth: `docs/architecture.md`, `AGENTS.md`, `src/llmkit/cli/`, `pyproject.toml` (LiteLLM is pinned `1.102.2`; the task LLMKIT-002 title says 1.106.5 but the pin stayed 1.102.2 — the title is superseded), ADR-0001 (llmkit becomes a layer over 9router: the own journal and the response cache go away — note in the report that the code still has both, E-001 added the cache).
4. Do not change code, tests, dependency pins, `.agents/` task files or the changelog.
5. Language: the living docs stay in their current language (README/architecture Russian, CONTEXT English); ADRs in Russian like 0001–0003.
6. Update the pointers that name `docs/prd.md` as the specification: `AGENTS.md` (line «Спецификация v1 — docs/prd.md…»), `README.md` (line with «Спецификация: docs/prd.md»), `docs/architecture.md` §Зависимости («Сверх раздела 2 docs/prd.md не добавлять»). After the move no living doc may point at `docs/prd.md`. `AGENTS.md` keeps only pointers.

## Report

A table: every section of `docs/prd.md` → destination (file, ADR number, idea number, research record, drop + reason). Then a list of the ideas created (id + one line), the ADRs created, and the sections proposed as drops with their text verbatim. The last line: `antagor layout check` output.

The file `docs/prd.md` is deleted at the end only if every one of its sections is in that table. When `AGENTS.md` is edited, run `antagor memory-check` and quote its output in the report.

## Read first

- `docs/prd.md`
- `docs/adr/0001-nadstroyka-nad-9router.md`
- `docs/architecture.md`
- `AGENTS.md`
- `pyproject.toml`

## Out of scope

- Code, tests, dependency pins, the changelog, .agents/ task files
- Implementing ADR-0001 (own journal and cache stay until its own epic)
