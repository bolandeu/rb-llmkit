---
id: LLMKIT-012
title: 'Key lookup as in cli-generator: env, then the OS keyring, then a clear error'
status: cancelled
attempts: 2
blocked: false
blocked_reason: null
phase: red
tests_hash: null
publish_stage: null
created_by: architect
approved_by: architect
worker: pi
type: bugfix
owns_paths:
- src/llmkit/keys.py
- src/llmkit/health.py
- src/llmkit/cli/auth.py
- pyproject.toml
- uv.lock
test_paths:
- tests/test_keys.py
- tests/test_health.py
- tests/test_deps.py
- tests/conftest.py
docs: none
tools: []
worker_args: null
class: standard
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
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
---

LLMKIT-010 removed the keyring step from src/llmkit/keys.py: the gateway key now comes only from the env var named by routing.key_env. The organisation's contract says otherwise (sysadmin docs/adr/0001-local-secrets-by-reference.md and docs/usage/secrets.md): the order is an explicit env variable, then the OS store (Keychain on macOS, Secret Service on Linux through Python keyring, one code path for both), then a clear error; no Doppler. The cli-generator template is the reference implementation: template/src/{{ package_name }}/credentials/manager.py keeps one JSON blob per provider under the keyring service '<namespace>:<provider>' with the provider as the account, reads env '<NAMESPACE>_<PROVIDER>_<FIELD>' first, treats a keyring error as 'env only' with a single debug line, and never branches by OS. llmkit's names already line up: namespace llmkit, service 'llmkit:<provider>', account '<provider>', field api_key, env LLM_9ROUTER_API_KEY. Restore that step in keys.py, keep the value out of logs, JSON and the journal, and let llm auth status --json report source env|keychain|missing with source_ref ('LLM_9ROUTER_API_KEY' or 'keychain service llmkit:9router'). A locked or unavailable store is an access error, not a missing key; a wrong key never falls through to another source.

## Acceptance

- Given a key stored in the OS keyring as service 'llmkit:9router', account '9router', value JSON {"api_key": "..."}, When llm ask runs and no env var is set, Then the call reaches the gateway and llm auth status --json reports source keychain with source_ref 'keychain service llmkit:9router' [check: tests/test_keys.py]
- Given a key in both the env var and the keyring, When a command resolves it, Then the env value wins and auth status reports source env with source_ref 'LLM_9ROUTER_API_KEY' [check: tests/test_keys.py]
- Given neither source holds a key, When a command needs it, Then it exits 3 with AUTH_MISSING naming the env var and the keyring service, and auth status reports source missing [check: tests/test_health.py]
- Given the keyring raises (headless Linux, no Secret Service, locked store), When the env var is set, Then the call works, nothing crashes and one debug line says the store is unavailable; without the env var the error is an access error, not 'key missing' [check: tests/test_keys.py]
- Given the project, When its dependencies and import are checked, Then keyring is a runtime dependency, tests/test_deps.py no longer pins its absence, and import llmkit stays under 300 ms [check: tests/test_deps.py]

## How to test

Unit tests only, no real keychain: seam is llmkit.keys.resolve (and llmkit.health credential entries); substitute the keyring module with a fake (monkeypatch sys.modules['keyring'] or keyring.set_keyring) that answers get_password for 'llmkit:9router'/'9router' and raises keyring.errors.KeyringError for the unavailable case; data is a routing v1 dict with one 9router provider and the env var name from key_env.

## Basis

Reference implementation: cli-generator template/src/{{ package_name }}/credentials/manager.py (namespace, service '<ns>:<provider>', env '<NS>_<PROVIDER>_<FIELD>', keyring error -> env only, one debug line, no OS branches). Contract: sysadmin docs/adr/0001-local-secrets-by-reference.md and docs/usage/secrets.md. Existing shape of the entry (service 'llmkit:<provider>', account provider, JSON api_key) is what llmkit wrote before 0.14.0, so stored keys keep working.

## Read first

- `src/llmkit/keys.py`
- `src/llmkit/health.py`

## Out of scope

- Doppler and any cloud source
- Writing to the keyring: no 'llm keys set' command returns
- Legacy env names (OPENROUTER_API_KEY and friends)
- Moving other repositories onto the new API

## Feedback

### Attempt 1: out of the task's bounds (the changes were reverted)

- `docs/architecture.md`
- `tests/conftest.py`

### Attempt 2: out of the task's bounds (the changes were reverted)

- `docs/architecture.md`

### Blocked: aborted

Red phase: test files only (tests/test_keys.py, tests/test_health.py, tests/test_deps.py, tests/conftest.py). docs/architecture.md is a green-phase file; the promise is off for now and comes back before your green submit. Reuse the kept patches instead of rewriting.
