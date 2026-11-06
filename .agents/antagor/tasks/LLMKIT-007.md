---
id: LLMKIT-007
title: 'Sort docs/backlog.md: every item to an idea, or a drop with its proof'
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
- docs/backlog.md
- README.md
test_paths: []
docs:
- docs/backlog.md
tools: []
worker_args: null
decision: false
visual: null
review: true
depends_on: []
budget_usd: null
epic: E-002
spec_refs: []
checks: manual
resident: null
tool: null
pr: null
translation: 'Разобрать docs/backlog.md: каждый пункт → идея (antagor idea add) или
  выброс с доказательством; что уже сделано или противоречит ADR — в отчёт. Файл удаляется
  в конце.'
---

## What this task is

`docs/backlog.md` is a plan: phases, deferred work and known technical debt. A plan is not one of the four doc kinds, so the file is sorted and deleted. Each item becomes an idea of this project's list (`antagor idea add --text "…"`), one per item; an item already done or already contradicted by an ADR is not an idea — it goes to the report as a drop for the Human.

## Rules

1. Walk the file item by item: every `##` section and every bullet under it, including «Не привязано к конкретной фазе» and «Известный технический долг».
2. Check each item against today's code and docs before writing the idea: `README.md`, the architecture doc, `CONTEXT.md`, `docs/adr/` (0001 — llmkit is a layer over 9router, the own journal and the response cache go away, `stream: true` always; 0002 — routing is data; 0003 — one journal database), the changelog, `src/llmkit/`, `.agents/antagor/tasks/`, `antagor idea list`.
   - Already done → drop with the proof (file, line, release).
   - Contradicted by an ADR → drop, naming the ADR (for example an item that keeps the own journal or the response cache alive is contradicted by ADR-0001; the gateway section's «шлюз — доступ, llmkit — логика» split is superseded by ADR-0001, say which parts survive: the `openai_compatible` provider entry and the concrete models instead of combos).
   - Still pending → an idea, one per item, one or two lines, with the backlog section as the source in the text. A phase that is one piece of work (for example «перевод intentree») is one idea, its bullets are the idea's text, not separate ideas.
   - **Do not run `antagor idea add`**: `.agents/antagor/ideas/` is Antagor's own folder, a change there from the task's worktree never reaches main. Write every pending item into the report with the exact text the Architect will pass to `antagor idea add --text "…"` (one block per idea, ready to copy).
3. Do not propose an idea that duplicates one already in `antagor idea list` (the list is empty today; if it changed, note the duplicate in the report).
4. Do not change code, tests, dependency pins, `.agents/` task files or the changelog. Update `README.md` where it points at `docs/backlog.md` as the plan (§ «Что дальше» and the header).
5. The file `docs/backlog.md` is deleted at the end only if every item is in the report.

## Report

A table: backlog item → «idea» (with its ready `--text`) | drop + reason (with the proof: file/line/release/ADR). Then the list of ready `antagor idea add --text "…"` commands, one per idea, and the sections proposed as drops with their text verbatim. The last line: `antagor layout check` output and `antagor idea list` (titles only).

## Out of scope

- Code, tests, dependency pins and the changelog.
- Creating the ideas themselves: the Architect runs `antagor idea add` on main from the report.
- Implementing ADR-0001: its own epic comes later.
