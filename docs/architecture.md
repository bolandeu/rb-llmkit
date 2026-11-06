# Архитектура llmkit

LLM-вызовы идут только через шлюз 9router (ADR-0001). Своего состояния у llmkit
нет: ни базы, ни журнала, ни кэша ответов, ни прайса, ни транспортов подписок —
всё это у шлюза. Расходы llmkit только читает из журнала шлюза.

## Структура модулей

```text
src/llmkit/
  routing.py    routing v1: провайдеры шлюза и цепочка данными; RoutingInvalid с JSON Pointer
  contracts/    routing-v1.schema.json + векторы — публичный контракт (в колесе)
  legacy.py     `llm routing import`: config.toml < 0.8 → routing (встроенные дефолты 0.7 — здесь)
  config.py     настройки вызова: дефолты кода → LLMKIT_* → LlmKit(...) (файлов нет)
  keys.py       ключ шлюза: имя переменной из routing; значение — только из окружения
  gateway/      клиент шлюза: POST /chat/completions (JSON и SSE), probe для doctor
  core.py       LlmKit: ask / generate / ask_many и sync-обёртки
  models.py     Task, Attempt, Answer, Stats, Outcome — данные задачи и ответа
  callutil.py   помощники вызова: сообщения задачи и разбор JSON
  usage.py      журнал шлюза (usageHistory): чтение только на чтение, отчёт по ключам
  errors.py     исключения; EXIT_CODES — коды выхода CLI
  template.py   render(): шаблон промпта mustache (combustache), строгий, без экранирования HTML
  health.py     `llm auth status`: ключ шлюза и его проверка
  doctor.py     `llm doctor`: версия, конфиг, routing, доступность шлюза
  opencli.py    `llm describe --json`: документ OpenCLI (из шаблона cli-generator)
  data_files.py файл routing в каталоге конфигурации — для describe
  _sync.py      запуск корутины из синхронного кода
  cli/          команда `llm` — см. cli-conventions.md
```

Удалено вместе со своим состоянием и доступом: `db/`, `cache.py`, `transports/`,
`providers.py`, `cli/db.py`, `cli/serve.py`, `cli/keys.py`.

## Ленивые импорты

`httpx` и `pydantic` импортируются лениво, внутри функций пути вызова: `import
llmkit` обязан оставаться быстрым (порог — 300 мс, проверка — команда в корневом
AGENTS.md).

## Классификация ошибок

`cli/output.py` переводит исключения ядра в коды конверта: `KeyMissing` — 3,
`GatewayUnavailable` и `AllModelsFailed` — 5, `RoutingMissing`/`RoutingInvalid`/
`ConfigError`/`TemplateError` — 2, чужие — 1. Ошибок слоя БД больше нет.

## Журнал расходов — у шлюза, только чтение

Своего журнала у llmkit нет. `llm cost` читает SQLite шлюза 9router: таблица
`usageHistory` (строка на запрос; `timestamp` — ISO 8601 UTC, `apiKey`,
`promptTokens`, `completionTokens`, `cost`). Файл открывается `mode=ro`: llmkit
не пишет его, не мигрирует и не оставляет рядом журнала транзакций. Потребителя
различает ключ шлюза из `apiKey`. Путь — `LLMKIT_GATEWAY_DB`, по умолчанию
`~/.9router/db/data.sqlite`; нет файла или он не читается — `GATEWAY_DB_UNAVAILABLE`,
выход 5, подсказка называет путь.

## CLI-контракт и шаблон cli-generator

- `llm describe --json` — документ OpenCLI для каталога инструментов и Windmill
  (шаблон v1.5.6: `opencli.py`, `data_files.py`, `cli/describe.py`, `_distribution.TEMPLATE_VERSION`).
  В `x-rb-data` — только `routing.json` в `user_config_dir`; таблиц и
  представлений нет. `x-rb-env` — `LLM_<PROVIDER>_API_KEY`, `LLMKIT_ROUTING_FILE`,
  `LLMKIT_GATEWAY_DB`, `LLMKIT_LOG_LEVEL`; в `EXIT_CODES` нет 4 и 6.
  После правки команд — `uv run pytest --snapshot-update` и просмотр
  `tests/snapshots/describe.json`.
- Контракты потребителей — `tests/contracts/<потребитель>/llmkit.yaml` (копии из
  репо потребителя, не править); механика из шаблона v1.8.1. Офлайн-данные для
  `run` — `tests/contracts/fixtures.yaml` (плейсхолдеры → `tests/contracts/data/`)
  и фикстура `contract_offline` в `tests/conftest.py` (фейковый шлюз).
  Кейс не проходит из-за поведения CLI — не подгонять контракт, сказать
  пользователю. Кейсы `view` не проверяются: своей базы у llmkit нет.
- Единственное отличие шаблонных скриптов — поиск команд в
  `scripts/check_command_docstrings.py` (`src/*/cli/*.py`, `with guard(ctx):`).

## Ключи

Не логируются и не пишутся на диск библиотекой; `.env`-файлы не используются.
В routing — только имя переменной (`key_env`), значение — никогда; связки
ключей ОС и старых имён переменных нет. Ключ и переменные шаблона не попадают
в ответ `--json`.

## Routing

Встроенных провайдеров и уровней нет (0.8.0). `LlmKit(routing=...)` проверяет
routing при создании (цепочка необязательна); нет routing — `RoutingMissing` при
первом вызове. Библиотека env не читает; CLI берёт `--routing` (JSON или файл),
иначе `LLMKIT_ROUTING_FILE`, иначе файл `routing.json` в каталоге настроек
пользователя (`cli/runtime.routing_spec`). Проверка — `routing.parse`: pydantic
плюс то, что JSON Schema не выражает (протокол — только шлюз, имя модели не
пустое); контрактные векторы гоняет tests/test_routing.py и против llmkit, и
против JSON Schema.

## Стиль

Ruff: `line-length = 120`, набор правил — в `pyproject.toml`.

## Зависимости

Сверх раздела 2 `docs/prd.md` не добавлять. Вызов провайдера — только `httpx`,
своего HTTP-клиента и SDK провайдеров нет.
