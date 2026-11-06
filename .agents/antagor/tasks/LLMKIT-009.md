---
id: LLMKIT-009
title: 'Gateway client: ask, generate and ask_many through 9router over httpx'
status: in_progress
attempts: 1
blocked: true
blocked_reason: needs_scope
phase: green
tests_hash: 6b82e19ada9d10a3add888ab5e17b61d5e6897b83a2efdb4b11fe5d9f655e977
publish_stage: null
created_by: architect
approved_by: human
approved_words: Tvrdí
worker: pi
type: feature
owns_paths:
- src/llmkit/core.py
- src/llmkit/callutil.py
- src/llmkit/providers.py
- src/llmkit/chain.py
- src/llmkit/routing.py
- src/llmkit/models.py
- src/llmkit/errors.py
- src/llmkit/__init__.py
- src/llmkit/contracts/
- src/llmkit/gateway/__init__.py
- src/llmkit/gateway/client.py
- src/llmkit/gateway/sse.py
- src/llmkit/gateway/parse.py
- src/llmkit/cli/ask.py
- src/llmkit/cli/models.py
- src/llmkit/cli/routing.py
- src/llmkit/cli/doctor.py
- src/llmkit/cli/output.py
- tests/conftest.py
- tests/test_gateway.py
- tests/test_core.py
- tests/test_chain.py
- tests/test_providers.py
- tests/test_routing.py
- tests/test_doctor.py
- tests/test_cli.py
- tests/test_ci.py
- tests/data/
- tests/contracts/fixtures.yaml
- scripts/quality_bench.py
- src/llmkit/cli/runtime.py
- src/llmkit/db/normalize.py
- src/llmkit/doctor.py
- src/llmkit/transports/decisions.py
- pyproject.toml
test_paths:
- tests/test_gateway.py
- tests/test_core.py
- tests/test_routing.py
- tests/test_chain.py
- tests/test_ci.py
- tests/test_doctor.py
- tests/conftest.py
- tests/data/gateway_combo.sse
- tests/data/gateway_opencode_go.json
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
translation: 'Клиент шлюза на httpx: ask/generate/ask_many только через 9router, всегда
  stream true, разбор JSON и SSE, served_model/provider/cost из ответа, JSON по схеме
  с повтором без Instructor; своя цепочка ретраев убирается.'
---

## What must work

llmkit reaches models only through the 9router gateway, over httpx, with no LiteLLM and no Instructor.

- Routing names one openai_compatible provider: the gateway base URL and the name of an environment variable that holds its key. Model names are passed verbatim, exactly as written in the gateway settings, combos included; no provider/model split, no prefix added or cut.
- Every call sends stream true, because the gateway journals only streamed calls. The answer comes either as one JSON body or as an SSE stream (a non-streamed request is answered with content-type text/event-stream too; the body is a JSON line and data: [DONE]).
- The answer carries the text or the schema value, the served model (the model field of the gateway answer), the provider and the cost (usage.cost) when the gateway gives them. A missing provider and cost 0 are valid answers, not errors.
- ask validates a pydantic schema: the request asks for JSON by schema, the answer is validated, an invalid answer is retried a bounded number of times with the validation error text added, and after the last try the call fails with the error kind the CLI already maps to an exit code.
- Gateway unreachable, HTTP error, timeout and empty answer become the existing error kinds with their exit codes and a hint that names the gateway.
- llmkit runs no chain and no fallback of its own: one call is one attempt. The chain and the retry of the chain belong to the gateway.
- llm doctor --json checks the gateway: its reachability and the configured routing; healthy false names the failed check.
- Import stays under 300 ms; neither litellm nor instructor is imported by any code path.

## What not to build

A provider registry of llmkit, price tables, per-provider protocols, keyring lookups for provider keys, a retry chain, a cache.

## Acceptance

- Given a fake gateway that answers one request as a JSON body and another as an SSE stream, When lm ask --json and lm generate --json run, Then the answer, served_model, provider and cost_usd come from the gateway fields and the exit code is 0 [check: tests/test_gateway.py]
- Given an answer with no provider and cost 0, When that call succeeds, Then provider is null, cost_usd is 0.0 and no error is raised [check: tests/test_gateway.py]
- Given a schema ask answered with invalid JSON twice and a valid object third, When the call runs, Then three requests are sent, the retry carries the validation error text, and the result is the validated object [check: tests/test_core.py]
- Given a schema ask that never validates, When the retries are exhausted, Then the call fails with the existing invalid-answer error and its exit code [check: tests/test_core.py]
- Given a gateway that refuses the connection, When a call runs, Then it fails with the gateway-unavailable error, its exit code and a hint naming the gateway URL [check: tests/test_gateway.py]
- Given a routing entry that is not openai_compatible or that still carries prices, When the routing is loaded, Then validation refuses it with the JSON Pointer of the field [check: tests/test_routing.py]
- Given one completed call, When the request log of the fake gateway is read, Then exactly one request was sent and no second model was tried [check: tests/test_chain.py]
- Given the package, When it is imported, Then litellm and instructor are not in sys.modules and the import takes under 300 ms [check: tests/test_ci.py]
- Given lm doctor --json, When the gateway answers and when it does not, Then healthy is true and false respectively and the failed check names the gateway [check: tests/test_doctor.py]

## How to test

Unit and integration without network: an httpx transport stub returns recorded gateway bodies; data: recorded JSON and SSE answers of a combo and of an opencode-go call kept under tests/data.

## Basis

Reuse the error kinds and EXIT_CODES as they are, the guard/emit CLI pattern, and the isolated fixture; follow docs/cli-conventions.md.

## Read first

- `src/llmkit/core.py`
- `src/llmkit/routing.py`
- `src/llmkit/callutil.py`
- `docs/adr/0001-nadstroyka-nad-9router.md`
- `src/llmkit/errors.py`

## Out of scope

- Media and non-chat endpoints; removing the database, journal, cache, transports and serve; documents.
- Moving other repositories to the new API.

## Feedback

### Attempt 1: out of the task's bounds (the changes were reverted)

- `tests/contracts/data/routing.json`
- `tests/contracts/data/routing_all_broken.json`
- `tests/contracts/data/routing_first_broken.json`
- `tests/snapshots/describe.json`
- `tests/snapshots/help/ask.txt`
- `tests/snapshots/help/decide.txt`
- `tests/snapshots/help/json.txt`
- `tests/test_cache.py`
- `tests/test_chatgpt.py`
- `tests/test_cost.py`
- `tests/test_decide.py`
- `tests/test_flows.py`
- `tests/test_health.py`
- `tests/test_render_cli.py`
- `tests/test_routing_default.py`
- `tests/test_subscriptions.py`
- `tests/conftest.py`
- `tests/test_gateway.py`

### Answer to question #1

> Green phase froze tests/test_gateway.py, but six of its cases cannot pass against the frozen tests/conftest.py: test_model_name_goes_verbatim calls kit(fake, routing=...) while the file's kit() already passes routing= (TypeError: got multiple values for keyword argument 'routing'), and the five CLI cases patch runtime.build_kit with a kit that has no routing, so llm ask exits 2 ROUTING_MISSING while the cases expect exit 0 with gateway fields and exit 5 for gateway errors.
> Question: Who fixes tests/test_gateway.py: this task or the task that owns the test suite?
> Options:
> 1. Thaw tests/test_gateway.py for these six cases and fix them here
> 2. Keep it frozen: the red checks stay red and LLMKIT-010 fixes the file
> Recommended: Thaw tests/test_gateway.py for these six cases and fix them here

Option 1: thaw tests/test_gateway.py; its six cases are the task's own test defects (kit() already passes routing=, and the CLI cases patch runtime.build_kit with a kit that has no routing) — fix them here, keep the intended behaviour of the acceptance items

### Answer to finding #2

> The check 'uv run pytest -q' cannot be green for LLMKIT-009: 6 modules fail at collection on files this task must not touch (test_cost.py, test_decide.py, test_health.py, test_render_cli.py, test_routing_default.py, test_subscriptions.py import llmkit.providers and llmkit.transports.decisions, both deleted by ADR-0001), and 13 more cases fail on reverted fixtures and snapshots (test_cache.py 2, test_chatgpt.py 1, test_contracts.py 6, test_describe.py 1, test_help.py 4). tests/ is LLMKIT-010's path; the green phase froze these files for LLMKIT-009. Remaining 6 red cases are the frozen-test defects of question #1.

Check narrowed for this task: the state layer (providers, transports.decisions, cache, db tests, snapshots) is deleted by LLMKIT-010, which also restores a green full suite and ty. Here: only the modules of this task's acceptance, plus ruff/format.
