---
id: LLMKIT-002
title: 'LiteLLM 1.106.5: the critical vulnerability GHSA-7hp6-4w63-5g45 of 1.102.1
  is gone, the release audit is green'
status: queue
attempts: 0
blocked: true
blocked_reason: check_broken
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: human
approved_words: утверждаю
worker: claude-code
type: chore
owns_paths:
- pyproject.toml
- uv.lock
- docs/prd.md
test_paths: []
docs:
- docs/prd.md
tools: []
worker_args: null
class: mechanical
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- uv lock --check
- osv-scanner scan source --lockfile uv.lock
resident: null
tool: null
pr: null
translation: 'LiteLLM 1.106.5: в 1.102.1 критическая уязвимость GHSA-7hp6-4w63-5g45,
  аудит выпуска снова зелёный. Точный пин в pyproject.toml → 1.106.5, uv lock, упоминания
  в docs/prd.md.'
---

The Human asked to update LiteLLM to the latest release (28.10.2026). The release gate's vulnerability audit fails on uv.lock: litellm 1.102.1 has GHSA-7hp6-4w63-5g45 (CVSS 9.9), fixed in 1.102.2; the latest is 1.106.5. Change the exact pin in pyproject.toml to litellm==1.106.5 (the project pins LiteLLM exactly, docs/prd.md), relock with uv lock --upgrade-package litellm, and update the two pin mentions in docs/prd.md (they still say 1.102.0). The relock also moves boto3/botocore 1.43.98 -> 1.43.120, filelock 4.2.4 -> 3.32.7 (LiteLLM's own bound) and adds h2, hpack, hyperframe: keep them as uv resolves them. The full test suite and rb-release check must stay green. If a LiteLLM API the code uses changed between 1.102 and 1.106, fix the call in the smallest way and say so in the report.

## Read first

- `pyproject.toml`
- `docs/prd.md`

## Out of scope

- No other dependency is bumped on purpose; only what uv's relock of LiteLLM moves.
- No change of llmkit's own behaviour, options or output.
