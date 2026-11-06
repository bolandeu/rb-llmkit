# Архитектура llmkit

## Структура модулей

```text
src/llmkit/
  routing.py    routing v1: провайдеры, цепочка, цены данными; RoutingInvalid с JSON Pointer
  contracts/    routing-v1.schema.json + векторы — публичный контракт (в колесе)
  legacy.py     `llm routing import`: config.toml < 0.8 → routing (встроенные дефолты 0.7 — здесь)
  config.py     настройки вызовов: дефолты кода → LLMKIT_* → LlmKit(...) (файлов нет)
  keys.py       ключи: key_env/LLM_<P>_API_KEY → старое имя (warning) → связка ключей ОС
  providers.py  провайдер routing + модель → аргументы LiteLLM
  chain.py      цепочки, классификация ошибок, ретраи и backoff
  cache.py      кэш ответов: таблица llmkit_cache в базе журнала, первая запись побеждает
  usage.py      журнал вызовов, отчёты, бюджеты — таблица llmkit_calls
  db/           слой БД: PostgreSQL из LLMKIT_DATABASE_URL или SQLite, миграции Alembic
  core.py       LlmKit: ask / generate / ask_many и sync-обёртки
  models.py     Task, Attempt, Answer, Stats, Outcome — данные задачи и ответа (реэкспорт из core)
  callutil.py   помощники вызова модели: разбор ответа, цена провайдера, ленивые LiteLLM и Instructor
  errors.py     исключения; EXIT_CODES — коды выхода CLI
  template.py   render(): шаблон промпта mustache (combustache), строгий, без экранирования HTML
  opencli.py    `llm describe --json`: документ OpenCLI (из шаблона cli-generator v1.5.6)
  data_files.py файлы в каталогах данных и кэша — для describe
  _sync.py      запуск корутины из синхронного кода
  transports/   провайдеры по подписке: свой acompletion вместо LiteLLM
    _common.py      ошибки Subscription* и сборка litellm.ModelResponse
    chatgpt_auth.py вход OAuth Codex, файл токенов, обновление под замком
    chatgpt.py      Responses API chatgpt.com/backend-api/codex, SSE
    claude_cli.py   вызов `claude -p`, чистое окружение, kill группы процессов
    decisions.py    модели решений OpenRouter (`LlmKit.decide`), POST на httpx
  cli/          команда `llm` — см. cli-conventions.md
scripts/smoke.py  реальные вызовы провайдеров (фаза 0)
```

## Ленивые импорты

`litellm`, `instructor`, `keyring` и `sqlalchemy`/`alembic` (слой БД) импортируются лениво, внутри функций
пути вызова: `import llmkit` обязан оставаться быстрым (порог — 300 мс,
проверка — команда в корневом AGENTS.md).

## Провайдеры по подписке

`providers.build` для `protocol` из `SUBSCRIPTION_PROTOCOLS` проверяет вход (файл
токенов / наличие CLI) и кладёт в `ModelCall.completion` функцию транспорта;
ядро зовёт её вместо `litellm.acompletion`. Подмена `LlmKit(completion=...)`
по-прежнему перекрывает всё — тесты сети не касаются.

## Классификация ошибок

Идёт по **имени класса** исключения (`chain.py`), чтобы модуль не тянул
litellm на импорте. `classify()` возвращает `None` для чужих исключений —
их ядро пробрасывает, а не маскирует под ошибку провайдера.

## База (cli-generator architecture.md §12)

- `LLMKIT_DATABASE_URL` задан → только PostgreSQL; недоступна → `DatabaseUnavailable`
  (выход 5), никогда не подмена на SQLite. Не задан → SQLite из `usage.path`
  (по умолчанию `usage.sqlite` в `platformdirs.user_data_dir("llmkit")`). Между
  базами — только `llm db import-sqlite`.
- PostgreSQL не мигрируется при открытии: только `llm db upgrade` выпущенной
  версией (advisory lock, одна транзакция). Отстала → `DatabaseNotMigrated`,
  неизвестная ревизия → `DatabaseTooNew` (`CLI_TOO_OLD`, выход 6).
- Каждая миграция совместима с кодом предыдущего релиза (expand/contract):
  сначала добавить (nullable/default), переключить код, удалить или переименовать
  старое — в следующем релизе. Переименование — добавить + скопировать + позже удалить.
- Имена — `llmkit_*` в `public`; другим инструментам — только `llmkit_v1_*`;
  новая форма — `llmkit_v2_*` рядом. Представления объявлены в `db/tables.py`
  `views` (колонки с типами и `comment=`) — их публикует `llm describe --json`,
  а tests/test_db.py сверяет с базой после миграций; у таблиц —
  `info={"kind": "data" | "cache"}`. Ключи связи — `db/normalize.py`, колонкой
  рядом с исходным текстом.
- Местные отличия от шаблона cli-generator v1.4.6: пакет `src/llmkit/db/` вместо
  `core/` (модуль `core.py` здесь — `LlmKit`), ошибки БД библиотечные — в
  `src/llmkit/errors.py`, SQLite мигрируется под `BEGIN IMMEDIATE` (файл
  открывают несколько процессов: wp-bulk, antagor, `llm`), нет `db push`
  (расходы с Mac в прод не отправляются) и `doctor`.
- Тесты на PostgreSQL — только `scripts/pg_test.sh -q tests/test_db.py`: свой
  контейнер, порт от Docker, удаляется после; не фиксированный порт и не чужой сервер.

## CLI-контракт и шаблон cli-generator

- `llm describe --json` — документ OpenCLI для каталога инструментов и Windmill
  (шаблон v1.5.6: `opencli.py`, `data_files.py`, `cli/describe.py`, `_distribution.TEMPLATE_VERSION`).
  Отличия: в `x-rb-data` есть `user_cache_dir` (кэш ответов) и `user_config_dir`
  (routing по умолчанию), `DataFile.dir`; `x-rb-env` — ключи встроенных
  провайдеров, `LLMKIT_*` конфига, база, `CLAUDE_COMMAND`; в `EXIT_CODES` нет 4.
  После правки команд — `uv run pytest --snapshot-update` и просмотр
  `tests/snapshots/describe.json`.
- Контракты потребителей — `tests/contracts/<потребитель>/llmkit.yaml` (копии из
  репо потребителя, не править); механика из шаблона v1.8.1. Офлайн-данные для
  `run` — `tests/contracts/fixtures.yaml` (плейсхолдеры → `tests/contracts/data/`)
  и фикстура `contract_offline` в `tests/conftest.py` (фейковый провайдер
  `contract`). Кейс не проходит из-за поведения CLI — не подгонять контракт,
  сказать пользователю.
- Единственное отличие шаблонных скриптов — поиск команд в
  `scripts/check_command_docstrings.py` (`src/*/cli/*.py`, `with guard(ctx):`).

## Ключи

Не логируются и не пишутся на диск библиотекой; `.env`-файлы не используются.
В routing — только имя переменной (`key_env`), значение — никогда; в журнал
расходов и ответ `--json` ключи и переменные шаблона не попадают.

## Routing

Встроенных провайдеров и уровней нет (0.8.0). `LlmKit(routing=...)` проверяет
routing при создании (цепочка необязательна: её может дать `Task.chain`); нет
routing — `RoutingMissing` при первом вызове. Библиотека env не читает; CLI берёт
`--routing` (JSON или файл), иначе `LLMKIT_ROUTING_FILE`, иначе файл `routing.json`
в каталоге настроек пользователя (`cli/runtime.routing_spec`). Проверка — `routing.parse`:
pydantic плюс то, что JSON Schema не выражает (ссылки цепочки и цен на описанных
провайдеров); контрактные векторы гоняет tests/test_routing.py и против llmkit, и
против JSON Schema.

## Стиль

Ruff: `line-length = 120`, набор правил — в `pyproject.toml`.

## Зависимости

Сверх раздела 2 `docs/prd.md` не добавлять.
