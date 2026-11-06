# Архитектура llmkit

llmkit — надстройка над шлюзом 9router (ADR-0001). Вызовы моделей идут только
через шлюз. Своего состояния у llmkit нет: ни своей базы, ни своего журнала
расходов, ни справочника цен, ни доступа к провайдерам — это у шлюза. Расходы
llmkit только читает из журнала шлюза.

## Структура модулей

```text
src/llmkit/
  routing.py    routing v1: провайдер шлюза и цепочка данными; RoutingInvalid с JSON Pointer
  contracts/    routing-v1.schema.json + векторы — публичный контракт (в колесе)
  legacy.py     `llm routing import`: config.toml < 0.8 → routing (встроенные дефолты 0.7 — здесь)
  config.py     настройки вызова: дефолты кода → LLMKIT_* → LlmKit(...) (файлов нет)
  keys.py       ключ шлюза: имя переменной из routing; значение — только из окружения
  gateway/
    client.py   HTTP-клиент шлюза: метод на семейство эндпоинтов, ошибки GatewayUnavailable
    parse.py    ответ шлюза → типизированный результат: Reply, ImageResult, VideoResult и прочие
    sse.py      сборка ответа из потока text/event-stream
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
    surface.py  общее команд поверхности шлюза: клиент из routing, конверт, файл ответа
    image.py audio.py video.py embeddings.py web.py model.py chat.py   семейства шлюза
```

## Поверхность шлюза

Один метод клиента и одна команда CLI на семейство; ответ типизирован в
`gateway/parse.py`, формат провайдера llmkit не разбирает.

| Семейство | Эндпоинты шлюза | Команда |
|---|---|---|
| чат | `/v1/chat/completions`, `/v1/responses`, `/v1/responses/compact`, `/v1/messages`, `/v1/messages/count_tokens`, `/v1/systemone`, `/v1/api/chat`, `/v1beta/models` | `llm ask`, `llm json`, `llm chat *` |
| картинки | `/v1/images/generations` | `llm image generate` |
| речь | `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/voices` | `llm audio *` |
| видео | `/v1/videos/generations`, `/v1/videos/edits`, `/v1/videos/extensions`, `/v1/videos/{id}` | `llm video *` |
| эмбеддинги | `/v1/embeddings` | `llm embeddings create` |
| поиск и страница | `/v1/search`, `/v1/web/fetch` | `llm web *` |
| модели | `/v1/models`, `/v1/models/info`, `/v1/models/{model}` | `llm model *` |

Адрес — `base_url` провайдера routing; `/v1beta` берётся от корня адреса.
Картинка и речь приходят байтами: `--out` пишет файл, `--json` отдаёт путь.

## Публичный API

`LlmKit.ask` возвращает `Answer` (`models.py`): `data`, `model`, `served_model`,
`provider`, `attempts`, токены, `cost_usd`, `latency_ms`, `warnings`, `ok`.
`Task` — `user`, `system`, `messages`, `schema` (pydantic-класс или JSON Schema),
`default`, `temperature`, `max_tokens`, `timeout`, `retry`, `id`. Синхронные
обёртки — `ask_sync`, `generate_sync`, `ask_many_sync`; `generate` не бросает
ошибку, а возвращает `None` и пишет её в лог.

## Ленивые импорты

`httpx` и `pydantic` импортируются лениво, внутри функций пути вызова: `import
llmkit` обязан оставаться быстрым (порог — 300 мс, проверка — команда в корневом
AGENTS.md).

## Классификация ошибок

`cli/output.py` переводит исключения ядра в коды конверта: `KeyMissing` — 3,
`GatewayUnavailable` и `AllModelsFailed` — 5, `RoutingMissing`/`RoutingInvalid`/
`ConfigError`/`TemplateError` — 2, чужие — 1. Другого кода в пакете нет: список —
`errors.EXIT_CODES`, его проверяет tests/test_describe.py.

## Журнал расходов — у шлюза, только чтение

Своего журнала у llmkit нет. `llm cost` читает SQLite шлюза 9router: таблица
`usageHistory` (строка на запрос; `timestamp` — ISO 8601 UTC, `apiKey`,
`promptTokens`, `completionTokens`, `cost`). Файл открывается `mode=ro`: llmkit
не пишет его и не оставляет рядом файла транзакций. Потребителя различает ключ
шлюза из `apiKey`. Путь — `LLMKIT_GATEWAY_DB`, по умолчанию
`~/.9router/db/data.sqlite`; нет файла или он не читается — `GATEWAY_DB_UNAVAILABLE`,
выход 5, подсказка называет путь.

## Логи

Логгеры `llmkit.*`; строка INFO на вызов: модель, статус, токены, стоимость,
латентность. `LLMKIT_LOG_LEVEL` задаёт порог, `--verbose` в CLI — DEBUG.
Ключ шлюза в лог не попадает.

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
  пользователю. Кейсы `view` не проверяются: своего представления у llmkit нет.
- Единственное отличие шаблонных скриптов — поиск команд в
  `scripts/check_command_docstrings.py` (`src/*/cli/*.py`, `with guard(ctx):`).

## Ключи

Не логируются и не пишутся на диск библиотекой; `.env`-файлы не используются.
В routing — только имя переменной (`key_env`), значение — никогда; своего
хранилища ключей у llmkit нет. Ключ не попадает в ответ `--json`.

## Routing

Встроенных провайдеров и уровней нет (0.8.0). `LlmKit(routing=...)` проверяет
routing при создании (цепочка необязательна); нет routing — `RoutingMissing` при
первом вызове. Библиотека env не читает; CLI берёт `--routing` (JSON или файл),
иначе `LLMKIT_ROUTING_FILE`, иначе файл `routing.json` в каталоге настроек
пользователя (`cli/runtime.routing_spec`). Команды поверхности шлюза берут адрес
и ключ провайдера одной точкой — `cli/runtime.build_gateway`; провайдер в routing
один. Проверка — `routing.parse`: pydantic плюс то, что JSON Schema не выражает
(протокол — только шлюз, имя модели не пустое); контрактные векторы гоняет
tests/test_routing.py и против llmkit, и против JSON Schema.

## Стиль

Ruff: `line-length = 120`, набор правил — в `pyproject.toml`.

## Зависимости

Сверх `pyproject.toml` не добавлять. Вызов шлюза — только `httpx`, своего
HTTP-клиента и SDK провайдеров нет.
