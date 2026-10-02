# llmkit

Общий LLM-слой для инструментов: одна библиотека вместо шести самописных
клиентов. Даёт цепочки моделей с фолбэком, JSON по схеме, кэш ответов, учёт
токенов и стоимости с разбивкой по меткам и мягкие бюджеты.

Статус — см. [CHANGELOG.md](CHANGELOG.md) (сделано) и
[docs/backlog.md](docs/backlog.md) (план). Спецификация: [docs/prd.md](docs/prd.md).

## Что это даёт

| Возможность | Коротко |
|---|---|
| Цепочка моделей | `cheap = ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"]` — упала первая, отвечает вторая |
| Ретраи по типу ошибки | таймаут, 429 и 5xx повторяются на той же модели, отказ и «слишком длинный контекст» — сразу следующая |
| JSON по схеме | pydantic-класс через [Instructor](https://github.com/567-labs/instructor) или готовая JSON Schema (dict) |
| Кэш | SQLite, ключ по конкретной модели: ответ дешёвой модели не выдаётся за ответ сильной |
| Учёт | Журнал: одна строка на попытку, отчёты по меткам (`tool`, `niche`, …); SQLite или общая PostgreSQL (`LLMKIT_DATABASE_URL`, `llm db`) |
| Бюджеты | предупреждения при превышении дневного лимита; работа не прерывается |

## Установка

Дистрибутив называется **`rb-llmkit`** (стандарт tools §10: все наши пакеты —
`rb-<tool>`, чтобы не столкнуться с чужими пакетами на PyPI). Импорт
по-прежнему `import llmkit`, команда — `llm`. Ставить всегда по тегу `vX.Y.Z`
(последний — в `CHANGELOG.md`).

Как библиотека — в проект:

```bash
uv add "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"
```

Как команда `llm` — в систему. Старый инструмент под именем `llmkit` сначала
удалить, иначе два инструмента спорят за одну команду `llm`:

```bash
uv tool uninstall llmkit   # если стоял до переименования
uv tool install "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"
```

Репозиторий приватный, поэтому на машине нужен доступ к GitHub: `gh auth login`
(или ssh-ключ и адрес `git+ssh://git@github.com/bolandeu/llmkit`).

В `pyproject.toml` потребителя это выглядит так:

```toml
[project]
dependencies = ["rb-llmkit"]

[tool.uv.sources]
rb-llmkit = { git = "https://github.com/bolandeu/llmkit", tag = "vX.Y.Z" }
```

Переход потребителя со старого имени: в `dependencies` и ключе
`[tool.uv.sources]` заменить `llmkit` на `rb-llmkit`, затем один раз
`uv sync --reinstall-package rb-llmkit`. Обычный `uv sync` ставит новый
дистрибутив и удаляет старый вместе с общим скриптом `llm` — и `uv run llm`
молча запускает другой `llm` из PATH.

Требуется Python >= 3.11.


## CLI `llm`

Ставится вместе с пакетом (см. «Установка»). У всех команд есть `--json`
(конверт в stdout), диагностика идёт в stderr. Коды выхода по конвенциям
cli-builder: **0** — успех, **1** — непредвиденная ошибка, **2** — неверные
аргументы, **3** — нет ключа или входа в подписку, **5** — все модели цепочки упали.

```bash
llm                                  # справка: список команд, код выхода 0
llm ask "Столица Франции?" --level cheap --tag tool=notes
cat prompt.txt | llm ask --system "Отвечай кратко" --json
llm json "Разбери запрос" --schema schema.json          # в stdout только JSON-объект
llm models                           # провайдеры, уровни, есть ли ключ
llm keys set openrouter              # ввод скрыт; `--stdin` для автоматизации
llm keys status                      # источник ключа: config | env | keychain | subscription | none
llm auth login chatgpt               # вход в подписку ChatGPT (код устройства; --browser — через браузер)
llm auth status --check             # все доступы (ключи и подписки): откуда и работают ли; 3 — есть неверные
llm cost --by tool,niche --since 7d  # отчёт из журнала вызовов
llm config init                      # шаблон конфига; path | show
llm db status                        # база журнала: SQLite или PostgreSQL (LLMKIT_DATABASE_URL), ревизия схемы
llm db upgrade                       # миграции общей PostgreSQL (неявно она не мигрируется)
llm db import-sqlite --dry-run       # разовый переезд локального журнала в PostgreSQL
llm describe --json                  # контракт CLI документом OpenCLI: команды, коды выхода, env, данные
```

Полный список команд и флагов — `llm --help` и `llm <команда> --help`; справка
генерируется из кода и не расходится с ним. `llm serve` — фаза 4, пока отвечает
ошибкой с кодом выхода 2.

## Ключи

Ключи берутся в порядке: `api_key` в конфиге провайдера (не рекомендуется) →
переменная окружения → связка ключей ОС. `.env`-файлы не используются.

```bash
# вариант 1 — переменная окружения
export OPENROUTER_API_KEY=sk-or-...

# вариант 2 — связка ключей macOS
llm keys set openrouter
```

Шлюз [Ccode](https://www.ccode.dev/docs/quick-start) подключён как
`openai_compatible` (`https://all-api.ccode.dev/v1`): `llm keys set ccode` или
`export CCODE_API_KEY=...`, затем `llm ask "…" -m ccode/<модель>`. Список моделей
ключа — `curl -H "Authorization: Bearer $CCODE_API_KEY" https://all-api.ccode.dev/v1/models`.
Цены шлюза LiteLLM не знает: для точного учёта задайте `[providers.ccode.prices]`.

Шлюз [AnyModel](https://anymodel.org/api-docs.md) — так же, `openai_compatible`
(`https://anymodel.org/v1`): `llm keys set anymodel` или `export ANYMODEL_API_KEY=...`,
затем `llm ask "…" -m anymodel/am/gpt-5.6-terra`. Id модели — ровно как в каталоге,
с префиксом (`am/…`, `cc/…`): голый id — другой маршрут и другая цена. Каталог —
`curl -H "Authorization: Bearer $ANYMODEL_API_KEY" https://anymodel.org/v1/models`.
Шлюз считает в своих «токенах баланса», а не в $: для учёта в $ задайте
`[providers.anymodel.prices]`.

Стандартные имена переменных по виду провайдера: `OPENROUTER_API_KEY`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_API_KEY`;
`api_key_env` в конфиге перекрывает. В связке ключей значение лежит как
JSON `{"api_key": "..."}` в службе `llmkit:<провайдер>`.

## Подписки ChatGPT и Claude

Модели можно вызывать по подписке ChatGPT Plus/Pro и Claude Pro/Max, без
API-ключей. Провайдеры `chatgpt` и `claude` уже есть во встроенных дефолтах.

```bash
llm auth login chatgpt               # ссылка + одноразовый код; токены — в файле 0600
llm ask "Привет" -m chatgpt/gpt-5.5
claude auth login                    # вход держит сам Claude Code CLI
llm ask "Привет" -m claude/sonnet
```

- **ChatGPT** (`kind = "chatgpt"`): вход OAuth, как у Codex CLI; запросы идут в
  Responses API `chatgpt.com/backend-api/codex`. Файл токенов свой
  (`platformdirs.user_data_dir("llmkit")/chatgpt-auth.json`), не `~/.codex/auth.json`:
  refresh-токен одноразовый, два клиента на одном выбивали бы друг друга.
  Температура и `max_tokens` не отправляются — бэкенд подписки их отвергает.
- **Claude** (`kind = "claude_cli"`): вызов установленного `claude -p` без
  инструментов и сессий, в пустом каталоге. Токен читает сам CLI (`claude auth login`
  или `CLAUDE_CODE_OAUTH_TOKEN`); `ANTHROPIC_API_KEY` и прочие `ANTHROPIC_*` из
  окружения CLI не передаются, иначе вызов ушёл бы на платный ключ. Другой бинарь —
  `CLAUDE_COMMAND`. Температура игнорируется.
- JSON по схеме у обоих — нативный (`text.format` / `--json-schema`). Стоимость в
  журнале — 0 (оплачено подпиской), токены учитываются.
- Условия Anthropic ограничивают использование подписки вне Claude Code —
  проверьте их перед массовыми вызовами; риск блокировки аккаунта за пользователем.

## Конфиг

Слои (позже перекрывает раньше): дефолты в коде → пользовательский конфиг
(`platformdirs.user_config_dir("llmkit")`: на macOS — `~/Library/Application
Support/llmkit/config.toml`, на Linux — `~/.config/llmkit/config.toml` или
`$XDG_CONFIG_HOME/llmkit/config.toml`) → `.llmkit/config.toml` проекта
(ищется вверх от текущего каталога) → переменные `LLMKIT_CACHE`,
`LLMKIT_LOG_LEVEL` → аргументы `LlmKit(...)`. `LLMKIT_CONFIG=/путь/config.toml`
заменяет поиск файлов целиком — удобно для переносимого конфига между машинами.

Встроенные дефолты (`config.py: DEFAULTS`) уже включают провайдеров `openrouter`,
`ollama`, `ccode` (шлюз ccode.dev, ключ `CCODE_API_KEY`), `anymodel` (шлюз
anymodel.org, ключ `ANYMODEL_API_KEY`), `chatgpt` и `claude`
(подписки) и уровни `cheap`/`judge`/`strong` с примерными моделями — свой
`config.toml` не обязателен, если устраивает пример и ключи уже заведены.

```toml
[providers.openrouter]
kind = "openrouter"                 # openrouter | openai | anthropic | gemini | ollama | openai_compatible | chatgpt | claude_cli

[providers.ollama]
kind = "ollama"
base_url = "https://ollama.com"     # локальный: http://localhost:11434
[providers.ollama.prices]           # $ за 1M токенов; главнее цен LiteLLM
"gpt-oss:120b" = { input = 0.15, output = 0.60 }

[levels]                            # уровень = цепочка "провайдер/модель" по порядку
# Модели ниже — пример: набор выбираете вы. Слева от первого "/" — ключ из
# [providers], справа — имя модели у этого провайдера (у OpenRouter оно само
# содержит "/"). Упала первая модель — отвечает следующая.
cheap  = ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"]
judge  = ["openrouter/anthropic/claude-sonnet-4"]

[defaults]
level = "cheap"
temperature = 0.0
timeout = 120
max_tokens = 4096
concurrency = 6

[cache]
enabled = true
ttl_days = 30

[budget]                            # только предупреждения
daily_usd = 20.0
[budget.tags]
"tool=intentree" = 2.0

[retry]
timeout = 1
rate_limit = 2
server = 2
invalid_output = 2
```

## Примеры

### Текст: `generate`

Ошибок не бросает — при полном провале возвращает `None`.

```python
import asyncio
from llmkit import LlmKit

kit = LlmKit(tags={"tool": "antagor"})


async def main():
    text = await kit.generate("Одним словом: столица Франции?", system="Отвечай кратко")
    print(text)


asyncio.run(main())
```

Синхронно — `kit.generate_sync("…")`; работает и из кода, где event loop уже
запущен (тогда вызов уходит в отдельный поток).

### JSON по схеме: `ask`

```python
from pydantic import BaseModel
from llmkit import LlmKit, Task


class Verdict(BaseModel):
    intent: str
    confidence: float


kit = LlmKit()
answer = kit.ask_sync(
    Task(
        user="Запрос: «купить кофеварку». Определи намерение.",
        schema=Verdict,  # или готовая JSON Schema (dict)
        level="judge",
        tags={"tool": "intentree", "niche": "ved"},
        default=Verdict(intent="unknown", confidence=0.0),  # без него — AllModelsFailed
    )
)
print(answer.data.intent, answer.source, answer.model, answer.cost_usd)
```

`Answer` содержит `data`, `source` (`llm` | `cache` | `default`), `model`,
`provider`, `attempts` (по одной записи на попытку), токены, `cost_usd`,
`cost_known`, `latency_ms`, `warnings` и `ok`.

### Пачка задач: `ask_many`

Порядок результатов совпадает с порядком задач, упавшая задача не рвёт пачку,
параллельность ограничена `defaults.concurrency`.

```python
tasks = [Task(user=f"Тема: {t}. Одно предложение.") for t in темы]
answers = await kit.ask_many(
    tasks,
    concurrency=4,
    on_progress=lambda done, total, answer: print(f"{done}/{total} {answer.model}"),
)
```

### Модели решений: `decide`

Эндпоинт OpenRouter `/api/alpha/decisions`: модель отвечает на узкие
типизированные вопросы о состоянии (`noul`, `choice`, `score`) вероятностями, а
не текстом. Ключ, ретраи, журнал и бюджет — как у `ask`; кэша нет.

```python
answer = await kit.decide(
    "Help! My payouts have been failing for 3 days.",
    {
        "is_urgent": {
            "type": "noul",
            "instructions": "Does this message convey urgency?",
            "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"},
        }
    },
)
answer.data["is_urgent"]["noul"]  # 0.95 — словарь answers из ответа как есть
answer.served_model  # "typesafe/jev-1.13-20260917" — кто ответил за алиасом
```

Цепочка — уровень `decide` (по умолчанию `openrouter/~typesafe/jev-latest`),
допустимы только модели провайдера `kind = "openrouter"`. Цена берётся из
`usage.cost` ответа.

### Расходы

```python
for row in kit.usage.report(group_by=("tool", "niche"), since="7d"):
    print(row.keys, row.calls, round(row.cost_usd, 4))
print(kit.stats)  # итоги за время жизни экземпляра
```

## Решения и отвергнутые альтернативы

Полная таблица (LiteLLM, Instructor, кэш, ключи, конфиг, CLI, прокси) и
обоснование пина версии LiteLLM — в [docs/prd.md](docs/prd.md) §1.

## Что дальше

Планы и отложенное за пределы v1 — в [docs/backlog.md](docs/backlog.md).
Сделанное — в [CHANGELOG.md](CHANGELOG.md).

## Разработка

Базовые команды (`uv sync`, `uv run scripts/release.py --check`) и порядок
релиза — в [AGENTS.md](AGENTS.md). Дополнительно:

```bash
uv run llm --help                # CLI из исходников
uv run python scripts/smoke.py   # реальные вызовы, требует ключей
```
