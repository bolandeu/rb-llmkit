# Changelog

Обратный хронологический порядок. Файл не правится руками: каждое изменение
добавляет фрагмент `changelog.d/+<slug>.<type>.md`
(`uv run towncrier create +<slug>.<type>.md -c "..."`), а `scripts/release.py`
собирает их в раздел новой версии. Разделы по датам ниже — история до v0.2.0.
Планы и отложенное — в docs/backlog.md.

<!-- towncrier release notes start -->

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
