# llmkit

Общий LLM-слой для инструментов: одна библиотека вместо шести самописных
клиентов. Даёт цепочки моделей с фолбэком, JSON по схеме, кэш ответов, учёт
токенов и стоимости с разбивкой по меткам и мягкие бюджеты.

Статус — см. [docs/CHANGELOG.md](docs/CHANGELOG.md) (сделано) и
[docs/BACKLOG.md](docs/BACKLOG.md) (план). Спецификация: [docs/PRD.md](docs/PRD.md).

## Что это даёт

| Возможность | Коротко |
|---|---|
| Цепочка моделей | `cheap = ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"]` — упала первая, отвечает вторая |
| Ретраи по типу ошибки | таймаут, 429 и 5xx повторяются на той же модели, отказ и «слишком длинный контекст» — сразу следующая |
| JSON по схеме | pydantic-класс через [Instructor](https://github.com/567-labs/instructor) или готовая JSON Schema (dict) |
| Кэш | SQLite, ключ по конкретной модели: ответ дешёвой модели не выдаётся за ответ сильной |
| Учёт | SQLite-журнал: одна строка на попытку, отчёты по меткам (`tool`, `niche`, …) |
| Бюджеты | предупреждения при превышении дневного лимита; работа не прерывается |

## Установка

Как библиотека — в проект:

```bash
uv add "git+https://github.com/bolandeu/llmkit"
```

Как команда `llm` — в систему:

```bash
uv tool install "git+https://github.com/bolandeu/llmkit"
```

Репозиторий приватный, поэтому на машине нужен доступ к GitHub: `gh auth login`
(или ssh-ключ и адрес `git+ssh://git@github.com/bolandeu/llmkit`).

В `pyproject.toml` потребителя это выглядит так:

```toml
[project]
dependencies = ["llmkit"]

[tool.uv.sources]
llmkit = { git = "https://github.com/bolandeu/llmkit" }
```

Требуется Python >= 3.11.


## CLI `llm`

Ставится вместе с пакетом (см. «Установка»). У всех команд есть `--json`
(конверт в stdout), диагностика идёт в stderr. Коды выхода по конвенциям
cli-builder: **0** — успех, **1** — непредвиденная ошибка, **2** — неверные
аргументы, **3** — нет ключа, **5** — все модели цепочки упали.

```bash
llm                                  # справка: список команд, код выхода 0
llm ask "Столица Франции?" --level cheap --tag tool=notes
cat prompt.txt | llm ask --system "Отвечай кратко" --json
llm json "Разбери запрос" --schema schema.json          # в stdout только JSON-объект
llm models                           # провайдеры, уровни, есть ли ключ
llm keys set openrouter              # ввод скрыт; `--stdin` для автоматизации
llm keys status                      # источник ключа: config | env | keychain | none
llm cost --by tool,niche --since 7d  # отчёт из журнала вызовов
llm config init                      # шаблон конфига; path | show
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

Стандартные имена переменных по виду провайдера: `OPENROUTER_API_KEY`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_API_KEY`;
`api_key_env` в конфиге перекрывает. В связке ключей значение лежит как
JSON `{"api_key": "..."}` в службе `llmkit:<провайдер>`.

## Конфиг

Слои (позже перекрывает раньше): дефолты в коде → пользовательский конфиг
(`platformdirs.user_config_dir("llmkit")`: на macOS — `~/Library/Application
Support/llmkit/config.toml`, на Linux — `~/.config/llmkit/config.toml` или
`$XDG_CONFIG_HOME/llmkit/config.toml`) → `.llmkit/config.toml` проекта
(ищется вверх от текущего каталога) → переменные `LLMKIT_CACHE`,
`LLMKIT_LOG_LEVEL` → аргументы `LlmKit(...)`. `LLMKIT_CONFIG=/путь/config.toml`
заменяет поиск файлов целиком — удобно для переносимого конфига между машинами.

Встроенные дефолты (`config.py: DEFAULTS`) уже включают провайдеров `openrouter`
и `ollama` и уровни `cheap`/`judge`/`strong` с примерными моделями — свой
`config.toml` не обязателен, если устраивает пример и ключи уже заведены.

```toml
[providers.openrouter]
kind = "openrouter"                 # openrouter | openai | anthropic | gemini | ollama | openai_compatible

[providers.ollama]
kind = "ollama"
base_url = "https://ollama.com"     # локальный: http://localhost:11434
[providers.ollama.prices]           # $ за 1M токенов, если LiteLLM цену не знает
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
answer = kit.ask_sync(Task(
    user="Запрос: «купить кофеварку». Определи намерение.",
    schema=Verdict,                       # или готовая JSON Schema (dict)
    level="judge",
    tags={"tool": "intentree", "niche": "ved"},
    default=Verdict(intent="unknown", confidence=0.0),   # без него — AllModelsFailed
))
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

### Расходы

```python
for row in kit.usage.report(group_by=("tool", "niche"), since="7d"):
    print(row.keys, row.calls, round(row.cost_usd, 4))
print(kit.stats)   # итоги за время жизни экземпляра
```

## Решения и отвергнутые альтернативы

Полная таблица (LiteLLM, Instructor, кэш, ключи, конфиг, CLI, прокси) и
обоснование пина версии LiteLLM — в [docs/PRD.md](docs/PRD.md) §1.

## Что дальше

Планы и отложенное за пределы v1 — в [docs/BACKLOG.md](docs/BACKLOG.md).
Сделанное — в [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Разработка

Базовые команды (`uv sync`, `uv run pytest -q`, `uv run ruff check`) — в
[AGENTS.md](AGENTS.md). Дополнительно:

```bash
uv run llm --help                # CLI из исходников
uv run python scripts/smoke.py   # реальные вызовы, требует ключей
```
