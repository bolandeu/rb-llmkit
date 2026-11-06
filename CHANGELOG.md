# Changelog

All notable changes to this project are documented here. Versions follow
[SemVer](https://semver.org/) (while at `0.x`, a minor bump may break).

The changelog is written by `antagor publish`; don't edit it by hand.

## v0.14.0 — 2026-11-06

### E-003 — Overlay over 9router: gateway client, no own state, CLI for agents

llm and the Python API reach models only through the 9router gateway: a typed API, media wrappers and a CLI every agent can drive by --help and --json. llmkit keeps code only — no database, journal, response cache, price table, subscription transports or proxy of its own. antagor layout check is clean: the specification and the plan are gone, their content lives in living docs, ADRs and ideas.
Time: 6.9h since the epic was approved

- Gateway client: ask, generate and ask_many through 9router over httpx (LLMKIT-009)
- Nothing of its own left: state, transports and their commands out, dependencies pruned (LLMKIT-010)
- The rest of the gateway surface wrapped, documents rewritten and the specification and plan sorted (LLMKIT-011)

## v0.13.0 — 2026-11-06

### Main

- architect: protocol test command without the coverage gate (a task runs a subset of tests)
- architect: no own database — extended layer over 9router, CLI and help for agents (ADR-0001)
- onboard: method layout
- LLMKIT-IDEA-001: new
- architect: ADR — gateway journals streaming calls only, cost optional
- architect: ADR — what llmkit still is: code, no state
- architect: ADR — cost and served model come in the gateway response
- architect: ADR — no own usage journal, read the gateway's read-only
- architect: ADR — full 9router surface list, systemone and gemini endpoints
- architect: ADR — llmkit covers the whole 9router surface, media included
- architect: ADR — no response cache in llmkit
- architect: ADR — llmkit is a layer over 9router, model names verbatim
- architect: floor on deepseek-4.1-flash with effort max
- workers: pi for the worker, pi-glm for the reviewer


## v0.12.0 — 2026-10-29

### E-001 — Shared response cache in the usage database

Every worker that uses one LLMKIT_DATABASE_URL shares one cache: the same call gives the same answer, the second one is a free hit.
Time: 0.8h since the epic was approved

- Cache in the usage database (table, migration 0003, first write wins) (LLMKIT-003)
- Cache surfaces: config path, describe, doctor, docs (LLMKIT-004)
- Two-worker acceptance on PostgreSQL (LLMKIT-005)

## v0.11.1 — 2026-10-29

### Outside epics

- LiteLLM 1.106.5: the critical vulnerability GHSA-7hp6-4w63-5g45 of 1.102.1 is gone, the release audit is green (LLMKIT-002)

## v0.11.0 — 2026-10-24

### Outside epics

- ask_many(raise_on_error): raise AllModelsFailed, not ExceptionGroup, on Python 3.11.2 (LLMKIT-001)

## [0.10.0] - 2026-10-03

### Changed

- Стоимость вызовов по общей схеме инструментов (T175). `cost_source`: `provider` (списано провайдером: `usage.cost` ответа OpenRouter — теперь первым и в `ask`/`json`, как в `decide`) → `price_table` (цена × токены: `routing.prices`, затем справочник LiteLLM; прежние `routing` и `litellm`) → `null` (прежнее `unknown`; `cost: null`, предупреждение); `cache`, `subscription` — 0. Конверт `--json` ask/json/decide: новые `cost`, `cost_currency` ("USD"), `billable_requests` (платные вызовы: ответ получен, в т.ч. неразобранный JSON; отказы 429/5xx/4xx не считаются; таймаут не считается, хотя OpenRouter может его списать), `cost_total` (по всем платным попыткам); у кода 5 — `error.billable_requests`, `error.cost_total`, `error.cost_currency`. `cost_usd` = `cost` — устарело, уйдёт в 0.11. Библиотека: `Answer.billable_requests`, `Answer.cost_total`, `Attempt.cost_source`/`billable`, `Answer.cost_source` — `None` вместо `"unknown"`; `Stats.cost_usd` считает и платные упавшие попытки. Учёт: миграция 0002 — колонки `cost_source`, `billable` в `llmkit_calls` и в конце `llmkit_v1_calls` (Postgres — `llm db upgrade`).


## [0.9.1] - 2026-10-03

### Added

- CLI ищет routing по умолчанию: без `--routing` и `LLMKIT_ROUTING_FILE` — `routing.json` в `platformdirs.user_config_dir("llmkit")` (macOS `~/Library/Application Support/llmkit/`, Linux `~/.config/llmkit/`); права шире 600 — предупреждение в stderr. `ROUTING_MISSING` называет путь по умолчанию в `action`; `llm config path --json` — новое поле `routing_default`, `routing_file` учитывает файл по умолчанию; `llm describe` — `x-rb-data.user_config_dir`.


## [0.9.0] - 2026-10-03

### Added

- Конверт `--json` у `llm ask`, `llm json` и `llm decide` отдаёт `task_id` — тот же, что в `llmkit_calls.task_id` и `llmkit_v1_calls.task_id`: ссылка из результата вызова на строку учёта (Windmill: `llm_call_ref`). CLI теперь задаёт id каждому вызову (uuid4 hex); раньше `task_id` из CLI в учёте был пуст. В библиотеке без изменений: `Task.id` по-прежнему задаёт вызывающий.


## [0.8.1] - 2026-10-02

### Changed

- Дефолты кода — бывшие значения `config.toml` с Mac: `max_tokens` 16000 (было 4096), повторы `retry` timeout 0 / rate_limit 6 / server 6 / invalid_output 2 (было 1/2/2/2); кэш 30 дней и дневной бюджет $20 — как прежде. С 0.8.0 `config.toml` не читается, его содержимое переехало так: провайдеры и цены — в routing v1 (`llm routing import <config.toml>`), уровни — в цепочки (`routing.chain` или `-m`; `import` отдаёт их в `levels`), `[defaults]`/`[retry]`/`[cache]`/`[budget]` — дефолты кода, переопределение — флаги CLI (`--max-tokens`, `--timeout`, `--temperature`, `--no-retry`, `--no-cache`), аргументы `LlmKit(...)`/`LlmKit(config=...)` и env `LLMKIT_CACHE`, `LLMKIT_LOG_LEVEL`.


## [0.8.0] - 2026-10-02

### Added

- Routing v1: провайдеры, цепочка и цены приходят данными — `llm ask|json|decide --routing '<json>'|<файл>` (иначе `LLMKIT_ROUTING_FILE`), `LlmKit(routing=dict)`. Публичный контракт — `llmkit/contracts/routing-v1.schema.json` и векторы `routing-v1.vectors.json`. Ошибки: `ROUTING_MISSING` / `ROUTING_INVALID` (код 2, `error.path` — JSON Pointer поля); в библиотеке `RoutingMissing` (при первом вызове) и `RoutingInvalid`. Повторяемый `-m` — цепочка из CLI; вместе с `routing.chain` — «chain задана дважды». Ключи: `LLM_<ПРОВАЙДЕР>_API_KEY` (или `key_env`) → старое имя с предупреждением «rename to LLM_…» (один цикл) → связка `llmkit:<провайдер>`. Ответ `--json`: `model`, `served_model`, `chain_position`, `attempts[{model, error_code}]`, `provider`, `tokens_in`, `tokens_out`, `cost_usd` (null — цена неизвестна, предупреждение `price unknown for <model>`), `cost_source` (routing | litellm | provider | subscription | cache | unknown), `cache_hit`, `warnings`; у кода 5 — `error.attempts`. Новые команды: `llm routing validate <файл|json> [--providers-only]`, `llm routing import <config.toml>` (провайдеры и цены старого конфига вместе с бывшими встроенными, уровни отдельно в `levels`, ключи не переносятся). `--routing` у `llm models`, `llm keys status`, `llm auth status`.

### Removed

- **Ломающее (0.x → 0.8.0).** Встроенных провайдеров и уровней больше нет: `config.DEFAULTS` без providers/levels, `[levels]`, `defaults.level`, `Task.level`, `LlmKit(level=...)`, `generate/decide(level=...)`, `llm ask|json|decide --level` (код 2 с подсказкой «передайте цепочку: -m … или routing.chain»), `llmkit.load_config`. Файлы `config.toml` (пользовательский, проектный, `LLMKIT_CONFIG`) не читаются; `llm config init` удалён. Ключ в файле (`api_key`), `api_key_env`, `requires_key` ушли вместе с конфигом. Ответ `--json` ask/json/decide: вместо `source`, `prompt_tokens`, `completion_tokens`, `cost_known` — `cache_hit`, `tokens_in`, `tokens_out`, `cost_source`; у ask текст в `text` (было `data`). Нет ключа — `AUTH_MISSING` (было `AUTH_REQUIRED`) с `error.variable`. Потребители на <0.6 (wp-bulk, antagor) не затронуты до своего перехода.


## [0.7.0] - 2026-10-02

### Added

- Шаблоны промптов mustache (combustache): `llm render --template <файл|текст|-> --vars <json-файл|json> [--lenient] [--json]`, те же `--template/--vars/--lenient` у `llm ask`, `llm json`, `llm decide`; библиотечно — `llmkit.render(template, vars, strict=True)`. Экранирования HTML нет; по умолчанию строго: отсутствующая переменная — `TemplateVariableMissing` / код выхода 2 с `error.code = TEMPLATE_VARIABLE_MISSING` и `error.variable`. В метки учёта расходов идут `template` (имя файла, `inline` или `stdin`) и `template_sha256` (12 знаков), значения переменных — нет.

### Changed

- Шаблон cli-generator v1.5.6: TDD обязателен — новый шаг гейта `existing tests` (изменённые с последнего тега тесты), mutmut в группе `mutation`; `x-rb-template-version` в `llm describe --json` — v1.5.6.


## [0.6.1] - 2026-10-02

### Changed

- Шаблон cli-generator v1.5.5: корневой агент — `tools`, никто из агентов инструмента не пушит (релиз отчитывается `tools`, пушит dev после «да» пользователя); `x-rb-template-version` в `llm describe --json` — v1.5.5.


## [0.6.0] - 2026-10-02

### Added

- `llm describe --json` — контракт CLI документом OpenCLI (шаблон cli-generator v1.5.0): команды и флаги, коды выхода, env, таблицы и представление `llmkit_v1_calls`, файлы данных и кэша, внешние программы.


## [0.5.0] - 2026-10-01

### Changed

- Журнал расходов переехал на слой БД шаблона cli-generator v1.4.2: с `LLMKIT_DATABASE_URL` он пишется в общую PostgreSQL, без неё — в SQLite `usage.sqlite`, как раньше. Таблица `calls` при первом открытии переименовывается в `llmkit_calls` вместе со строками, поэтому llmkit во всех потребителях одной машины поднимать одновременно: v0.4.x после переименования писал бы в новую пустую `calls`. Новые команды `llm db status|upgrade|import-sqlite`; другие инструменты читают представление `llmkit_v1_calls`. Новые зависимости: sqlalchemy, alembic, psycopg.


## [0.4.3] - 2026-09-29

### Added

- **Провайдер `anymodel`** во встроенных дефолтах: шлюз anymodel.org как `openai_compatible` (`https://anymodel.org/v1`, ключ `ANYMODEL_API_KEY`, режим `TOOLS`). Модель — id из каталога шлюза с префиксом: `anymodel/am/gpt-5.6-terra`.


## [0.4.2] - 2026-09-28

### Added

- `LlmKit.decide(state, questions)` / `decide_sync` — модели решений OpenRouter (`/api/alpha/decisions`): вероятности по типизированным вопросам вместо текста. Тот же ключ OpenRouter, цепочка и ретраи, цена из ответа в журнал. Уровень `decide` по умолчанию — `openrouter/~typesafe/jev-latest`. Версия, которая реально ответила, — в `Answer.served_model` и новой колонке `served_model` журнала (старые базы дополняются сами).
- Команда `llm decide "состояние" --questions q.json [--json]` — вызов моделей решений из CLI; в `--json` конверт с `served_model`.


## [0.4.1] - 2026-09-27

### Changed

- litellm 1.102.0 → 1.102.1 (patch).

### Fixed

- Версия (`llm --version`, `auth status`) находится и у установки под старым именем дистрибутива `llmkit`, ещё не переустановленной как `rb-llmkit`.


## [0.4.0] - 2026-09-27

### Changed

- Дистрибутив переименован: `llmkit` → `rb-llmkit` (стандарт tools §10). Импорт `llmkit` и команда `llm` не меняются. Потребителям: в `dependencies` и `[tool.uv.sources]` заменить `llmkit` на `rb-llmkit` и один раз выполнить `uv sync --reinstall-package rb-llmkit`; глобальный инструмент — `uv tool uninstall llmkit`, затем `uv tool install "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"`.


## [0.3.0] - 2026-09-27

### Changed

- `llm auth status` переписан по общему контракту здоровья доступов (§8 стандарта): один отчёт по ключам API и подпискам с полями `tool`, `version`, `checked_at`, `credentials[]` вместо прежнего `providers[]` с `logged_in`; новые флаги `--check` (один бесплатный read-only вызов на провайдера, лимит 10 с) и `--provider`; код выхода 3 (`CREDENTIALS_UNHEALTHY`) при неверном или просроченном доступе. Ломающее изменение для тех, кто разбирал старый `--json`. Новый модуль `llmkit.health`.
- Переход на общий стандарт релизов tools: версия берётся из git-тега (`llm --version` печатает только номер версии, без префикса `llm`), changelog собирается из фрагментов `changelog.d/`, единый гейт `scripts/release.py --check`, у справки каждой команды есть пример и снапшот.


## 2026-09-27

- **Цена из конфига главнее LiteLLM** (`core._cost`): порядок теперь
  подписка → `providers.<p>.prices` → LiteLLM. Раньше у шлюза `ccode` LiteLLM
  узнавал вендорское имя модели и считал по прайсу вендора: замер antagor
  на 104 статьях gpt-5.6-sol — $11.75 в журнале против $0.62 по ценам конфига.

## 2026-09-24

- **Провайдер `ccode`** во встроенных дефолтах: шлюз ccode.dev как
  `openai_compatible` (`https://all-api.ccode.dev/v1`, ключ `CCODE_API_KEY`,
  режим Instructor `TOOLS`). Живой вызов не проверен — нет ключа.

## 2026-09-23

- **Подписки вместо API-ключей**: `kind = "chatgpt"` (OAuth Codex CLI, Responses
  API `chatgpt.com/backend-api/codex`) и `kind = "claude_cli"` (установленный
  `claude -p`). Порт решений iva-agent на Python: файл токенов 0600, обновление
  под замком с перечитыванием файла, повтор при 401, защита `account_id`;
  чистое окружение и убийство группы процессов у CLI. JSON по схеме нативно,
  стоимость 0. Команды `llm auth login|status|logout`, провайдеры `chatgpt` и
  `claude` во встроенных дефолтах. Claude проверен живым вызовом.
- **CLI**: `llm ask`/`llm json` получили флаг `--timeout` (переопределяет
  `defaults.timeout` на конкретный вызов, как уже работали `--temperature`
  и `--max-tokens`).
- **`Task.retry`** (новое поле, по умолчанию `True`) и флаг CLI `--no-retry`:
  `False` — ноль повторов на сбойной модели для этого вызова, сразу
  следующая в цепочке (включая ретраи Instructor на невалидном выводе).
  Тонкая настройка счётчиков `[retry]` по-прежнему только в конфиге —
  осознанно не стали городить per-call переопределение всех 4 категорий.

## 2026-09-21

- **Фаза 2 — CLI `llm`**: команды `ask`, `json`, `keys`, `models`, `cost`,
  `config`, заглушка `serve`. Тесты на `CliRunner`. (143a759)
- **Правки по ревью**: исправления в `core.py`, коды выхода CLI приведены к
  конвенциям cli-builder. (af4c72a)
- **Задание фазы 3**: подготовлен план перевода antagor на llmkit,
  `docs/phase3-antagor.md`. (4443943)
- **Фазы 0–1 — ядро**: `config`, `keys`, `providers`, `chain`, `cache`,
  `usage`, `core`. 137 тестов без сети, импорт `llmkit` ~80 мс, smoke-тест на
  реальных ключах (`docs/smoke-2026-09.md`), подтверждена работа Ollama Cloud
  через `ollama_chat/` + `api_base=https://ollama.com`. (abc006c)
