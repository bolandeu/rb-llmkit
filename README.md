# llmkit

Общий LLM-слой для инструментов: одна библиотека вместо шести самописных
клиентов. Даёт цепочки моделей с фолбэком, JSON по схеме, кэш ответов, учёт
токенов и стоимости с разбивкой по меткам и мягкие бюджеты.

Статус — см. [CHANGELOG.md](CHANGELOG.md) (сделано) и
[docs/backlog.md](docs/backlog.md) (план). Спецификация: [docs/prd.md](docs/prd.md).

## Что это даёт

| Возможность | Коротко |
|---|---|
| Routing данными | провайдеры, цепочка и цены — JSON routing v1 в вызове (`--routing`, `LlmKit(routing=...)`); встроенных провайдеров и уровней нет |
| Цепочка моделей | `"chain": ["ccode/gpt-5.6-terra", "openrouter/openai/gpt-4o-mini"]` — упала первая, отвечает вторая |
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
llm ask "Столица Франции?" --routing routing.json --tag tool=notes
llm ask "Привет" -m ccode/gpt-5.6-sol -m openrouter/openai/gpt-4o-mini   # цепочка из CLI
llm routing validate routing.json    # проверка перед сохранением; ROUTING_INVALID с путём к полю
llm routing import config.toml       # перенос config.toml llmkit < 0.8 (провайдеры, цены, уровни отдельно)
cat prompt.txt | llm ask --system "Отвечай кратко" --json
llm json "Разбери запрос" --schema schema.json          # в stdout только JSON-объект
llm render --template prompt.md --vars vars.json        # шаблон mustache; нет переменной — код 2
llm ask --template prompt.md --vars '{"city": "Москва"}'  # то же у json и decide; в учёт — имя и хэш шаблона
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
API-ключей. В routing это провайдеры с `protocol` `chatgpt` и `claude_cli`, без `key_env`.

```bash
llm auth login chatgpt               # ссылка + одноразовый код; токены — в файле 0600
llm ask "Привет" -m chatgpt/gpt-5.5   # routing: {"providers": {"chatgpt": {"protocol": "chatgpt"}}}
claude auth login                    # вход держит сам Claude Code CLI
llm ask "Привет" -m claude/sonnet    # routing: {"providers": {"claude": {"protocol": "claude_cli"}}}
```

- **ChatGPT** (`protocol: "chatgpt"`): вход OAuth, как у Codex CLI; запросы идут в
  Responses API `chatgpt.com/backend-api/codex`. Файл токенов свой
  (`platformdirs.user_data_dir("llmkit")/chatgpt-auth.json`), не `~/.codex/auth.json`:
  refresh-токен одноразовый, два клиента на одном выбивали бы друг друга.
  Температура и `max_tokens` не отправляются — бэкенд подписки их отвергает.
- **Claude** (`protocol: "claude_cli"`): вызов установленного `claude -p` без
  инструментов и сессий, в пустом каталоге. Токен читает сам CLI (`claude auth login`
  или `CLAUDE_CODE_OAUTH_TOKEN`); `ANTHROPIC_API_KEY` и прочие `ANTHROPIC_*` из
  окружения CLI не передаются, иначе вызов ушёл бы на платный ключ. Другой бинарь —
  `CLAUDE_COMMAND`. Температура игнорируется.
- JSON по схеме у обоих — нативный (`text.format` / `--json-schema`). Стоимость в
  журнале — 0 (оплачено подпиской), токены учитываются.
- Условия Anthropic ограничивают использование подписки вне Claude Code —
  проверьте их перед массовыми вызовами; риск блокировки аккаунта за пользователем.

## Routing v1 и настройки

С 0.8.0 файла конфига нет, `config.toml` не читается. Провайдеры, цепочка и цены
приходят **данными** в каждом вызове — routing v1 (схема
`src/llmkit/contracts/routing-v1.schema.json`, векторы `routing-v1.vectors.json` —
публичный контракт). Секретов в routing нет: только имена переменных с ключами.

```json
{
  "providers": {
    "ccode": {"protocol": "openai_compatible", "base_url": "https://all-api.ccode.dev/v1",
              "key_env": "LLM_CCODE_API_KEY", "mode": "TOOLS"},
    "openrouter": {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"}
  },
  "chain": ["ccode/gpt-5.6-terra", "openrouter/openai/gpt-4o-mini"],
  "prices": {"ccode/gpt-5.6-terra": {"input": 0.09, "output": 0.54}}
}
```

- `protocol`: openrouter | openai | anthropic | gemini | ollama | openai_compatible |
  chatgpt | claude_cli; `base_url` обязателен для ollama и openai_compatible.
- CLI: `--routing '<json>'` или `--routing <файл>` (не stdin — он для текста и
  шаблона); без него — файл из `LLMKIT_ROUTING_FILE`; без него — файл по
  умолчанию `routing.json` в каталоге конфигурации (`platformdirs.user_config_dir("llmkit")`:
  macOS — `~/Library/Application Support/llmkit/routing.json`, Linux —
  `~/.config/llmkit/routing.json`; путь — `llm config path`). Права шире 600 —
  предупреждение в stderr (ключей там нет, но файл личный). Нет ничего — код 2,
  `ROUTING_MISSING` с путём по умолчанию в `action`. Цепочку можно задать `-m` (повторяемый) при routing
  без `chain`; оба сразу — `ROUTING_INVALID` «chain задана дважды».
- Ключ: `key_env`, по умолчанию `LLM_<ПРОВАЙДЕР>_API_KEY` → старое имя
  (`OPENROUTER_API_KEY`, `CCODE_API_KEY`…; один цикл, с предупреждением «rename to
  LLM_…») → связка ключей `llmkit:<провайдер>` → код 3, `AUTH_MISSING` с именем
  переменной.
- Цена — стоимость по общей схеме инструментов (T175): `cost_source` — `provider`
  (списано провайдером, `usage.cost` ответа OpenRouter) → `price_table` (цена × токены:
  `routing.prices`, затем справочник LiteLLM — оба «таблица цен») → `null` (неизвестна:
  `cost: null`, предупреждение `price unknown for <модель>`); `cache` и `subscription` —
  `cost: 0`. Конверт `--json` ask/json/decide: `cost` (ответившей попытки),
  `cost_currency: "USD"`, `cost_source`, `billable_requests` (платные вызовы провайдера:
  ответ получен — в том числе пустой с токенами, отфильтрованный, неразобранный JSON;
  отказы 429/5xx/4xx/нет ключа — нет: OpenRouter их не списывает; подписка — считается,
  стоимость 0), `cost_total` (сумма по платным попыткам, `null` — цена хоть одной
  неизвестна). У кода 5 — `error.billable_requests`, `error.cost_total`. `cost_usd` = `cost`,
  устарело, уходит в 0.11 (Windmill читает его). Неясно: таймаут — OpenRouter может
  списать запрос, который дошёл до модели, — в `billable_requests` не считается;
  внутренние повторы Instructor (pydantic-схема в библиотеке) не видны — считается один.
- Перенос старого конфига: `llm routing import ~/Library/Application\ Support/llmkit/config.toml`
  — провайдеры (с адресами бывших встроенных) и цены в `routing`, уровни — отдельно
  в `levels` подсказкой для своих цепочек.

Настройки вызовов — дефолты в коде (температура 0, таймаут 120 с, `max_tokens`
16000, 6 параллельных, повторы: таймаут 0 / 429 и 5xx по 6, кэш 30 дней, дневной бюджет $20 — только предупреждение) →
`LLMKIT_CACHE`, `LLMKIT_LOG_LEVEL` → аргументы `LlmKit(...)` и флаги CLI
(`--temperature`, `--max-tokens`, `--timeout`, `--no-retry`, `--no-cache`).

## Примеры

### Текст: `generate`

Ошибок не бросает — при полном провале возвращает `None`.

```python
import asyncio
from llmkit import LlmKit

kit = LlmKit(routing=routing, tags={"tool": "antagor"})  # routing — dict по схеме v1


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


kit = LlmKit(routing=routing)
answer = kit.ask_sync(
    Task(
        user="Запрос: «купить кофеварку». Определи намерение.",
        schema=Verdict,  # или готовая JSON Schema (dict)
        chain=["openrouter/anthropic/claude-sonnet-4"],  # вместо routing.chain; провайдеры — из routing
        tags={"tool": "intentree", "niche": "ved"},
        default=Verdict(intent="unknown", confidence=0.0),  # без него — AllModelsFailed
    )
)
print(answer.data.intent, answer.source, answer.model, answer.cost_usd)
```

`Answer` содержит `data`, `source` (`llm` | `cache` | `default`), `model`
(элемент цепочки), `served_model` (версия от провайдера), `chain_position`,
`provider`, `attempts` (по одной записи на попытку: `cost_usd`, `cost_source`,
`billable`), токены, `cost_usd` (None — цена неизвестна), `cost_source`,
`billable_requests`, `cost_total`, `cache_hit`, `latency_ms`, `warnings` и `ok`.
Без routing экземпляр создаётся, а первый вызов бросает `RoutingMissing`.

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

Цепочка — из routing (например `["openrouter/~typesafe/jev-latest"]`),
допустимы только модели провайдеров с `protocol: "openrouter"`. Цена берётся из
`usage.cost` ответа (`cost_source: "provider"`).

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

Базовые команды (`uv sync`, гейт — шаг `rb-release check` в `.gitea/workflows/ci.yml`) и порядок
релиза — в [AGENTS.md](AGENTS.md). Дополнительно:

```bash
uv run llm --help                # CLI из исходников
uv run python scripts/smoke.py   # реальные вызовы, требует ключей
```
