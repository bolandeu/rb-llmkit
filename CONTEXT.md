# llmkit

One LLM layer for the user's tools: one gateway call, a typed answer and a spend report behind one `LlmKit` API and
the `llm` CLI. It replaces the hand-written LLM clients of the tools that call it, so routing and the shape of the
answer are decided in one place.

ADR-0001 made llmkit an overlay over the 9router gateway: the gateway holds the access to providers, the accounts and
the spend; llmkit keeps code — the typed API, the response parsing, the media wrappers and the CLI contracts.

## Glossary

**routing** (маршрутизация; routing v1, `routing.json`):
The data that tells llmkit where to call: the gateway provider and the chain of models. A versioned public contract
(`src/llmkit/contracts/routing-v1.schema.json`), not llmkit's own settings.
_Avoid_: config, settings, config.toml, profile

**provider** (провайдер):
One upstream service named in routing: a protocol (`openai_compatible`), a base URL and the name of an environment
variable that holds the key. Keeps no secret itself. The only provider is the gateway: one `openai_compatible` entry,
the provider keys live in 9router.
_Avoid_: backend, vendor, endpoint, integration

**chain** (цепочка):
The ordered models of the gateway. Only the first is asked: the order and the fallback are the gateway's.
_Avoid_: fallback list, pool, router

**attempt** (попытка):
One model call inside a chain; with one call to the gateway it is usually one attempt. Failed attempts of an invalid
answer stay in `Answer.attempts`, they are billed too.
_Avoid_: try, call (when a request row is meant)

**task** (`Task`):
The unit of `ask_many`: a prompt, a schema and an optional `default`.
_Avoid_: job, item, request, Antagor task

**answer** (`Answer`):
The parsed value llmkit returns for a task: the text or the value of the schema, with the model, cost and warnings.
_Avoid_: result, response (for the llmkit value)

**cost** (цена, `cost_usd`):
The money of one attempt, taken from the gateway's answer (`usage.cost`); `served_model` and `provider` come from the
same answer. llmkit keeps no table of its own.
_Avoid_: spend, expense

**served model** (фактическая модель, `served_model`):
The concrete model that answered when the asked name is an alias or a gateway combo.
_Avoid_: actual model, real model, resolved model

**gateway** (шлюз, 9router):
The external OpenAI-compatible gateway on `localhost:20128/v1` that holds accounts, OAuth subscriptions, quotas and the
spend. It is the only way to a model — llmkit calls it as one `openai_compatible` provider, executes no
fallback of its own and keeps no state of its own.
_Avoid_: proxy, router

**gateway surface** (поверхность шлюза):
The endpoint families llmkit wraps one command group each: chat shapes, images, audio, video, embeddings, search and
page fetch, models.
_Avoid_: API, endpoints, integrations

**media answer** (медиа-ответ):
The answer of an image, audio or video command: a URL or a written file, never a parse of a provider format.
_Avoid_: blob, binary, attachment

**readiness report** (`llm doctor`):
The checks a caller runs before work — version, settings, routing, gateway — as `healthy` plus a list of checks.
_Avoid_: health, status, diagnostics

**OpenCLI contract** (`llm describe`):
The `--json` document that publishes commands, exit codes and data files to the tools catalogue and Windmill; a diff
of its snapshot is a change of the tool's contract.
_Avoid_: schema, manifest, spec
