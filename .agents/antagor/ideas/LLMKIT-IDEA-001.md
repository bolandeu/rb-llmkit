---
id: LLMKIT-IDEA-001
title: Onboard llmkit to the method, finish the pi wiring
created: '2026-11-06T11:15:04+00:00'
source_project: antagor
source_path: /Users/bolandau/Work/antagor
status: new
benefit: 'llmkit stops drifting from the method: a decision root, sorted docs, honest
  references, and a pi Architect that knows its role, name and floor'
---

Bring llmkit in line with the Antagor method, with pi as the client.

State today: the project was set up in the Claude Code era. `.claude/settings.local.json` (role, hooks, 52 allow rules, deny rules) was removed on 6.11 — nothing may recreate it. `antagor layout check` reports gaps; `antagor memory-check` reports broken references.

Checklist:
1. `antagor layout check` with no gaps.
2. `docs/decisions.md` — who decides what and where each decision lives (the root the method points at). Absent now.
3. `CONTEXT.md` — terms of the project (layout check says "no terms yet").
4. Sort the five loose documents into the shapes the method allows: `docs/architecture.md`, `docs/backlog.md`, `docs/cli-conventions.md`, `docs/prd.md`, `docs/testing.md`. A plan, backlog or brief becomes an idea or a task, a decision becomes an ADR, a living document is registered in `[docs] living`, research goes to `docs/research/`.
5. Fix the 21 broken references in `AGENTS.md` (`antagor memory-check` lists them: `core/opencli.py`, `commands/describe.py`, `db/tables.py`, `cache.py`, `architecture.md`, `runs/`, `core/db.py`, `db/tables.py`, `cache.py`, …).
6. pi must work as the Architect client, end to end: pane name `llmkit` from the folder name, role and project root in the system prompt, news once per session, model and effort reported for the floor, root agents listed for addressing, audit and the deny/ask rules honoured. Verify after restarting the pane: the agent answers with its project, its Herdr name and pane, and `antagor -C <root> architect check` says `verdict: ok`.
7. Mode stays `fast` unless the Human changes it.

Out of scope: no new mechanism in Antagor's core; a gap that only llmkit has is worked around in llmkit.
