---
id: LLMKIT-001
title: 'ask_many(raise_on_error): raise AllModelsFailed, not ExceptionGroup, on Python
  3.11.2'
status: publish
attempts: 2
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: claude-code
type: bugfix
owns_paths:
- src/llmkit/core.py
- tests/test_core.py
- docs/architecture.md
- src/llmkit/callutil.py
- src/llmkit/models.py
test_paths:
- tests/test_core.py
docs: none
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- uv run pytest tests/test_core.py -q --no-cov
resident: null
tool: null
pr: null
---

CI (Debian, Python 3.11.2) fails tests/test_core.py::test_ask_many_can_raise and ::test_raise_on_error_cancels_remaining_tasks: ask_many(raise_on_error=True) raises an ExceptionGroup wrapping AllModelsFailed, because the code re-raises inside an `except*` block (src/llmkit/core.py, ask_many). Locally (3.11.14) they pass. Fix: in ask_many catch BaseExceptionGroup with a plain `except`, take `group.subgroup(AllModelsFailed)`; if None re-raise the group, else `raise failed.exceptions[0] from None`. A reference diff is at /private/tmp/claude-501/-Users-bolandau-Work-tools-llmkit/33e8e04b-760f-40fe-bd5c-f3da1815fc16/scratchpad/core-fix.diff. The two existing tests must stay unchanged. Every Python module touched needs a module docstring (already there).

## Acceptance

- Given ask_many(raise_on_error=True) and a chain where every model fails, When it runs, Then AllModelsFailed itself is raised, not an ExceptionGroup [check: tests/test_core.py]

## How to test

Existing tests tests/test_core.py::test_ask_many_can_raise and test_raise_on_error_cancels_remaining_tasks; they fail only on Python 3.11.2 (CI), so the red run is CI run 517 job 705.

## Out of scope

- No other behaviour change; no test edits.

## Feedback

### Attempt 1: file docstring

- src/llmkit/core.py 994 lines > limit 800: split it by meaning (one capability, one module)

### Attempt 2: file docstring

- update the docstring of src/llmkit/core.py: -Answer -Attempt -Stats -Task
