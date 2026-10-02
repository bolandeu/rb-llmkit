# Архитектура llmkit

## Структура модулей

```
src/llmkit/
  routing.py    routing v1: провайдеры, цепочка, цены данными; RoutingInvalid с JSON Pointer
  contracts/    routing-v1.schema.json + векторы — публичный контракт (в колесе)
  legacy.py     `llm routing import`: config.toml < 0.8 → routing (встроенные дефолты 0.7 — здесь)
  config.py     настройки вызовов: дефолты кода → LLMKIT_* → LlmKit(...) (файлов нет)
  keys.py       ключи: key_env/LLM_<P>_API_KEY → старое имя (warning) → связка ключей ОС
  providers.py  провайдер routing + модель → аргументы LiteLLM
  chain.py      цепочки, классификация ошибок, ретраи и backoff
  cache.py      SQLite-кэш ответов (локальный, вне слоя БД)
  usage.py      журнал вызовов, отчёты, бюджеты — таблица llmkit_calls
  db/           слой БД: PostgreSQL из LLMKIT_DATABASE_URL или SQLite, миграции Alembic
  core.py       LlmKit: ask / generate / ask_many и sync-обёртки
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
  (выход 5), никогда не подмена на SQLite. Не задан → SQLite из `usage.path`.
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

## Ключи

Не логируются и не пишутся на диск библиотекой; `.env`-файлы не используются.
В routing — только имя переменной (`key_env`), значение — никогда; в журнал
расходов и ответ `--json` ключи и переменные шаблона не попадают.

## Routing

Встроенных провайдеров и уровней нет (0.8.0). `LlmKit(routing=...)` проверяет
routing при создании (цепочка необязательна: её может дать `Task.chain`); нет
routing — `RoutingMissing` при первом вызове. Библиотека env не читает; CLI берёт
`--routing` (JSON или файл) или `LLMKIT_ROUTING_FILE`. Проверка — `routing.parse`:
pydantic плюс то, что JSON Schema не выражает (ссылки цепочки и цен на описанных
провайдеров); контрактные векторы гоняет tests/test_routing.py и против llmkit, и
против JSON Schema.

## Стиль

Ruff: `line-length = 120`, набор правил — в `pyproject.toml`.

## Зависимости

Сверх раздела 2 `docs/prd.md` не добавлять.
