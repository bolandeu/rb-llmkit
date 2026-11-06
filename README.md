# llmkit

Общий LLM-слой для инструментов: один клиент к шлюзу 9router вместо нескольких
самописных. Даёт вызов модели, текст или JSON по схеме, пачку задач и чтение
расходов из журнала шлюза.

Своего состояния у llmkit нет: ни базы, ни журнала, ни кэша ответов, ни
прайса, ни доступа к провайдерам напрямую — всё это у шлюза (ADR-0001).
Провайдеры, ключи, подписки и кэш живут в 9router.

Статус — [CHANGELOG.md](CHANGELOG.md). План — [docs/backlog.md](docs/backlog.md).

## Что это даёт

| Возможность | Коротко |
|---|---|
| Routing данными | провайдер шлюза и цепочка моделей — JSON routing v1 в вызове (`--routing`, `LlmKit(routing=...)`); встроенных провайдеров нет |
| Один вызов — один запрос | цепочку, фолбэк и кэш исполняет шлюз; llmkit просит первую модель |
| JSON по схеме | JSON Schema ответа уходит в шлюз как `response_format`; невалидный ответ повторяется с текстом ошибки |
| Пачка задач | `ask_many` с ограничением параллельности, падение одной задачи не рвёт пачку |
| Расходы | `llm cost` читает журнал шлюза (`usageHistory`) только на чтение, по ключам потребителей |

## Установка

Дистрибутив называется **`rb-llmkit`** (стандарт tools §10). Импорт —
`import llmkit`, команда — `llm`. Ставить всегда по тегу `vX.Y.Z`.

```bash
uv add "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"        # в проект
uv tool install "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"  # команда в систему
```

Репозиторий приватный, поэтому на машине нужен доступ к GitHub: `gh auth login`
(или ssh-ключ и адрес `git+ssh://git@github.com/bolandeu/llmkit`).

```toml
[project]
dependencies = ["rb-llmkit"]

[tool.uv.sources]
rb-llmkit = { git = "https://github.com/bolandeu/llmkit", tag = "vX.Y.Z" }
```

Требуется Python >= 3.11.

## CLI `llm`

У всех команд есть `--json` (конверт в stdout), диагностика идёт в stderr.
Коды выхода: **0** — успех, **1** — непредвиденная ошибка, **2** — неверные
аргументы или routing, **3** — нет переменной с ключом шлюза, **5** — шлюз
недоступен, ответил ошибкой, ответ невалиден или журнал расходов не читается.

```bash
llm                                      # справка: список команд, код выхода 0
llm ask "Столица Франции?" --routing routing.json --tag tool=notes
llm ask "Привет" -m "Deep Sec" -m opencode-go   # цепочка из CLI, если в routing нет chain
cat prompt.txt | llm ask --system "Отвечай кратко" --json
llm json "Разбери запрос" --schema schema.json   # в stdout только JSON-объект
llm render --template prompt.md --vars vars.json # шаблон mustache; нет переменной — код 2
llm ask --template prompt.md --vars '{"city": "Москва"}'
llm models                                # провайдеры routing, источник ключа, цепочка
llm routing validate routing.json         # проверка перед сохранением; ROUTING_INVALID с путём к полю
llm routing import config.toml            # перенос config.toml llmkit < 0.8
llm auth status --check                   # ключ шлюза: откуда и работает ли; 3 — ключ не принят
llm cost --since 7d                       # расходы из журнала шлюза, по ключам
llm config show                           # итоговые настройки вызова
llm doctor --json                         # готовность: версия, конфиг, routing, шлюз
llm describe --json                       # контракт CLI документом OpenCLI
```

Полный список команд и флагов — `llm --help` и `llm <команда> --help`; справка
генерируется из кода и не расходится с ним.

## Ключ шлюза

Ключ берётся только из окружения: имя переменной называет routing (`key_env`, по
умолчанию `LLM_<ПРОВАЙДЕР>_API_KEY`). Связки ключей и `.env`-файлов у llmkit нет.
Нет переменной — код 3, `AUTH_MISSING` с её именем.

```bash
export NINEROUTER_API_KEY=sk-...
```

## Routing v1

Файла конфига нет. Провайдер шлюза и цепочка приходят данными в каждом вызове —
routing v1 (схема `src/llmkit/contracts/routing-v1.schema.json`, векторы
`routing-v1.vectors.json` — публичный контракт). Секретов в routing нет: только
имя переменной с ключом.

```json
{
  "providers": {
    "9router": {"protocol": "openai_compatible", "base_url": "http://localhost:20128/v1",
                "key_env": "NINEROUTER_API_KEY"}
  },
  "chain": ["Deep Sec", "opencode-go"]
}
```

- `protocol` — только `openai_compatible` с адресом шлюза; других провайдеров у
  llmkit нет.
- `chain` — имена моделей шлюза строками, как в его настройке (комбо — одна
  строка). Порядок и фолбэк исполняет шлюз: llmkit просит первую.
- CLI: `--routing '<json>'` или `--routing <файл>` (не stdin — он для текста и
  шаблона); без него — `LLMKIT_ROUTING_FILE`; без него — `routing.json` в каталоге
  конфигурации (`platformdirs.user_config_dir("llmkit")`; macOS —
  `~/Library/Application Support/llmkit/routing.json`). Права шире 600 —
  предупреждение в stderr. Нет ничего — код 2, `ROUTING_MISSING` с путём по умолчанию.
- Цепочку можно задать `-m` (повторяемый) в routing без `chain`; оба сразу —
  `ROUTING_INVALID` «chain задана дважды».

Настройки вызова — дефолты в коде (температура 0, таймаут 120 с, `max_tokens`
16000, 6 параллельных, повторы невалидного ответа 2) → `LLMKIT_LOG_LEVEL` →
аргументы `LlmKit(...)` и флаги CLI (`--temperature`, `--max-tokens`, `--timeout`,
`--no-retry`).

## Расходы

`llm cost` читает SQLite шлюза: `LLMKIT_GATEWAY_DB`, по умолчанию
`~/.9router/db/data.sqlite`. Файл открывается только на чтение — llmkit его не
пишет и не мигрирует. Строки отчёта — по ключу шлюза (`apiKey`); потребителя
различает его собственный ключ. Нет файла — код 5, `GATEWAY_DB_UNAVAILABLE` с путём.

```bash
llm cost --since 7d --json   # rows[] по ключам и total
```

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

Синхронно — `kit.generate_sync("…")`; работает и там, где event loop уже запущен
(вызов уходит в отдельный поток).

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
        tags={"tool": "intentree", "niche": "ved"},
        default=Verdict(intent="unknown", confidence=0.0),  # без него — AllModelsFailed
    )
)
print(answer.data.intent, answer.source, answer.model, answer.cost_usd)
```

`Answer` содержит `data`, `source` (`llm` | `default`), `model` (запрошенная
строка модели), `served_model` (что назвал шлюз), `provider`, `attempts` (по
записи на попытку: `cost_usd`, `cost_source`, `billable`), токены, `cost_usd`
(`None` — цены в ответе нет), `cost_source`, `billable_requests`, `cost_total`,
`latency_ms`, `warnings` и `ok`. Без routing экземпляр создаётся, а первый вызов
бросает `RoutingMissing`.

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

## Решения и отвергнутые альтернативы

[docs/prd.md](docs/prd.md) §1 и [docs/adr/](docs/adr/). Действующее решение —
ADR-0001: llmkit — надстройка над шлюзом 9router.

## Разработка

Команды разработки (`uv sync`, гейт `rb-release check` в `.gitea/workflows/ci.yml`)
и порядок релиза — в [AGENTS.md](AGENTS.md).

```bash
uv run llm --help                # CLI из исходников
```
