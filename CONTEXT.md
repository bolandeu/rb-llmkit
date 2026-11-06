# llmkit

One LLM layer for the user's tools: model chains, a response cache, cost accounting and budgets behind one
`LlmKit` API and the `llm` CLI. It replaces the hand-written LLM clients of the tools that call it, so routing,
retries, cache and spend are decided in one place.

## Glossary

**routing** (маршрутизация; routing v1, `routing.json`):
The data that tells llmkit where to call: providers, levels, the chain of models per level, prices. A versioned
public contract (`src/llmkit/contracts/routing-v1.schema.json`), not llmkit's own settings.
_Avoid_: config, settings, config.toml, profile

**provider** (провайдер):
One upstream service named in routing: a protocol (`openrouter`, `openai_compatible`, `claude_cli`…), a base URL and
the name of an environment variable that holds the key. Keeps no secret itself.
_Avoid_: backend, vendor, endpoint, integration

**level** (уровень):
A named chain of models — `cheap`, `judge`, `strong`; a caller asks a level, not a model.
_Avoid_: tier, class, profile, preset

**chain** (цепочка):
The ordered models of one level: the next is tried only after a classified failure of the previous one.
_Avoid_: fallback list, pool, router

**attempt** (попытка):
One model call inside a chain; one row of the journal.
_Avoid_: try, call (when the journal row is meant)

**task** (`Task`):
The unit of `ask_many`: a prompt, tags, a level and an optional budget of its own.
_Avoid_: job, item, request, Antagor task

**answer** (`Answer`):
The parsed value llmkit returns for a task: the text or the value of the schema, with the model, cost and cache flag.
_Avoid_: result, response (for the llmkit value)

**response cache** (кэш ответов, `src/llmkit/cache.py`):
Answers kept in the journal database under a key made from the exact request and the requested model, so the same
question is not paid twice; the first write wins. Off — the answer is asked again.
_Avoid_: disk cache, LLM cache, memo, storage

**journal** (журнал вызовов, `llmkit_calls`, `llmkit_v1_calls`):
One row per attempt with model, tags, tokens, cost and status; the source of `llm cost`, budgets and the reports of
other tools, which read only the view `llmkit_v1_calls`.
_Avoid_: usage, log, history, stats

**tags** (метки):
The caller's labels on a task (`tool`, `niche`, `level`…), the only way journal rows are grouped into reports and
budgets.
_Avoid_: labels, metadata, dimensions

**budget** (бюджет):
A spend limit — for a day, or for one task (`Task.budget_usd`); going over it warns today, it does not stop the call.
_Avoid_: quota, limit, cap

**cost** (цена, `cost_usd`, `cost_source`):
The money of one attempt and where the number came from: the provider's answer (`provider`), llmkit's price table
(`price_table`), a subscription (zero, `billable=false`) or a cache hit.
_Avoid_: price (of a model — that is the price table), spend, expense

**served model** (фактическая модель, `served_model`):
The concrete model that answered when the asked name is an alias or a gateway combo.
_Avoid_: actual model, real model, resolved model

**transport** (`src/llmkit/transports/`):
A provider reachable without an API key, through a subscription: the ChatGPT backend or the local `claude` CLI.
_Avoid_: proxy, adapter, plugin

**gateway** (шлюз, 9router):
The external OpenAI-compatible gateway on `localhost:20128/v1` that holds accounts, OAuth subscriptions and quotas;
llmkit reaches it as one more `openai_compatible` provider.
_Avoid_: proxy, router

**readiness report** (`llm doctor`):
The checks a caller runs before work — keys, database, routing, package version — as `healthy` plus a list of checks.
_Avoid_: health, status, diagnostics

**OpenCLI contract** (`llm describe`):
The `--json` document that publishes commands, exit codes and data files to the tools catalogue and Windmill; a diff
of its snapshot is a change of the tool's contract.
_Avoid_: schema, manifest, spec
