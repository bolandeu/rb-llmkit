# llmkit

One LLM layer for the user's tools: model chains, a response cache, cost accounting and budgets behind one
`LlmKit` API and the `llm` CLI. It replaces the hand-written LLM clients of the tools that call it, so routing,
retries, cache and spend are decided in one place.

ADR-0001 replaces the state layer of this list: the own providers, transports, journal, cache, price table and the
tags go to the 9router gateway; llmkit keeps code — the typed API, the response parsing, the media wrappers and the
CLI contracts. Terms marked _уходит (ADR-0001)_ describe code that is being removed; they are here until it is.

## Glossary

**routing** (маршрутизация; routing v1, `routing.json`):
The data that tells llmkit where to call: providers, levels, the chain of models per level, prices. A versioned
public contract (`src/llmkit/contracts/routing-v1.schema.json`), not llmkit's own settings.
_Avoid_: config, settings, config.toml, profile

**provider** (провайдер):
One upstream service named in routing: a protocol (`openrouter`, `openai_compatible`, `claude_cli`…), a base URL and
the name of an environment variable that holds the key. Keeps no secret itself. After ADR-0001 the only provider is
the gateway: one `openai_compatible` entry, the provider keys live in 9router.
_Avoid_: backend, vendor, endpoint, integration

**level** (уровень):
A named chain of models — `cheap`, `judge`, `strong`; a caller asks a level, not a model.
_Avoid_: tier, class, profile, preset

**chain** (цепочка):
The ordered models of one level: the next is tried only after a classified failure of the previous one.
_Avoid_: fallback list, pool, router

**attempt** (попытка):
One model call inside a chain; one row of the journal. _Уходит (ADR-0001)_: the gateway runs the chain, one call is
one attempt.
_Avoid_: try, call (when the journal row is meant)

**task** (`Task`):
The unit of `ask_many`: a prompt, tags, a level and an optional budget of its own.
_Avoid_: job, item, request, Antagor task

**answer** (`Answer`):
The parsed value llmkit returns for a task: the text or the value of the schema, with the model, cost and cache flag.
_Avoid_: result, response (for the llmkit value)

**response cache** (кэш ответов, `src/llmkit/cache.py`) — _уходит (ADR-0001)_:
Answers kept in the journal database under a key made from the exact request and the requested model, so the same
question is not paid twice; the first write wins. Removed: every `ask` is a call to the gateway.
_Avoid_: disk cache, LLM cache, memo, storage

**journal** (журнал вызовов, `llmkit_calls`, `llmkit_v1_calls`) — _уходит (ADR-0001)_:
One row per attempt with model, tags, tokens, cost and status; the source of `llm cost`, budgets and the reports of
other tools, which read only the view `llmkit_v1_calls`. Replaced by the gateway's own journal (`usageHistory`,
`usageDaily`, read-only SQLite); a consumer is told apart by its gateway API key.
_Avoid_: usage, log, history, stats

**tags** (метки) — _уходит (ADR-0001)_:
The caller's labels on a task (`tool`, `niche`, `level`…), the only way journal rows were grouped into reports and
budgets. Not kept: grouping is by the gateway API key of the consumer.
_Avoid_: labels, metadata, dimensions

**budget** (бюджет) — _уходит (ADR-0001)_:
A spend limit — for a day, or for one task (`Task.budget_usd`); going over it warns today, it does not stop the call.
llmkit keeps no spend of its own, so there is nothing to count a budget from.
_Avoid_: quota, limit, cap

**cost** (цена, `cost_usd`):
The money of one attempt, taken from the gateway's answer (`usage.cost`); `served_model` and `provider` come from the
same answer. `cost_source` and the price table are _уходят (ADR-0001)_.
_Avoid_: price (of a model — that is the price table), spend, expense

**served model** (фактическая модель, `served_model`):
The concrete model that answered when the asked name is an alias or a gateway combo.
_Avoid_: actual model, real model, resolved model

**transport** (`src/llmkit/transports/`) — _уходит (ADR-0001)_:
A provider reachable without an API key, through a subscription: the ChatGPT backend or the local `claude` CLI. The
subscriptions move to the gateway; llmkit keeps no transport of its own.
_Avoid_: proxy, adapter, plugin

**gateway** (шлюз, 9router):
The external OpenAI-compatible gateway on `localhost:20128/v1` that holds accounts, OAuth subscriptions and quotas;
after ADR-0001 it is the only way to a model — llmkit calls it as one `openai_compatible` provider, executes no
fallback of its own and keeps no journal, cache or price of its own.
_Avoid_: proxy, router

**readiness report** (`llm doctor`):
The checks a caller runs before work — keys, database, routing, package version — as `healthy` plus a list of checks.
_Avoid_: health, status, diagnostics

**OpenCLI contract** (`llm describe`):
The `--json` document that publishes commands, exit codes and data files to the tools catalogue and Windmill; a diff
of its snapshot is a change of the tool's contract.
_Avoid_: schema, manifest, spec
