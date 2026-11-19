# llmkit

Надстройка над шлюзом [9router](https://github.com/decolua/9router): вызовы моделей,
JSON по схеме и пачка задач — через шлюз, без своих клиентов провайдеров.
Даёт `LlmKit` в Python и команду `llm` для людей и агентов.

Своего состояния у llmkit нет: ни базы, ни журнала, ни хранения ключей. Доступ к
моделям, подписки, квоты и расходы — у шлюза (ADR-0001). Нужен запущенный 9router
на той же машине.

Статус — [CHANGELOG.md](CHANGELOG.md).

## Что это даёт

| Возможность | Коротко |
|---|---|
| Один вызов модели | `LlmKit.ask` / `generate`; цепочку, фолбэк и повторы исполняет шлюз |
| JSON по схеме | JSON Schema уходит в шлюз как `response_format`; невалидный ответ повторяется с текстом ошибки |
| Пачка задач | `ask_many` с ограничением параллельности, падение одной задачи не рвёт пачку |
| Вся поверхность шлюза | команды `llm image`, `audio`, `video`, `embeddings`, `web`, `model`, `chat` — по одной на семейство эндпоинтов |
| Расходы | `llm cost` читает журнал шлюза (`usageHistory`) только на чтение, по ключам потребителей |

## Установка

Дистрибутив называется **`rb-llmkit`**, импорт — `llmkit`, команда — `llm`.
Ставить всегда по тегу `vX.Y.Z`.

```bash
uv add "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"           # в проект
uv tool install "rb-llmkit @ git+https://github.com/bolandeu/llmkit@vX.Y.Z"  # команда в систему
```

Репозиторий приватный: на машине нужен доступ к GitHub (`gh auth login` или
ssh-ключ и адрес `git+ssh://git@github.com/bolandeu/llmkit`). Требуется Python >= 3.11.

## Ключ шлюза и routing

Ключ берётся только из окружения; имя переменной называет routing (`key_env`).
Нет переменной — код 3, `AUTH_MISSING` с её именем.

```bash
export NINEROUTER_API_KEY=sk-...
```

Провайдер шлюза и цепочка моделей приходят данными — routing v1 (схема
`src/llmkit/contracts/routing-v1.schema.json`). Секретов в routing нет.

```json
{
  "providers": {
    "9router": {"protocol": "openai_compatible", "base_url": "http://localhost:20128/v1",
                "key_env": "NINEROUTER_API_KEY"}
  },
  "chain": ["Deep Sec", "opencode-go"]
}
```

- `protocol` — только `openai_compatible` с адресом шлюза.
- `chain` — имена моделей шлюза строками, как в его настройке (комбо — одна
  строка). Порядок и фолбэк исполняет шлюз: llmkit просит первую.
- CLI: `--routing '<json>'` или `--routing <файл>`; без него — `LLMKIT_ROUTING_FILE`;
  без него — `routing.json` в каталоге конфигурации (`platformdirs.user_config_dir("llmkit")`,
  macOS — `~/Library/Application Support/llmkit/routing.json`). Нет ничего — код 2,
  `ROUTING_MISSING` с путём по умолчанию.
- Цепочку можно задать `-m` (повторяемый) в routing без `chain`; оба сразу —
  `ROUTING_INVALID` «chain задана дважды».

## CLI `llm`

У всех команд есть `--json` (конверт в stdout), диагностика идёт в stderr.
Коды выхода: **0** — успех, **1** — непредвиденная ошибка, **2** — неверные
аргументы или routing, **3** — нет переменной с ключом шлюза, **5** — шлюз
недоступен, ответил ошибкой или его журнал расходов не читается.

```bash
llm                                      # справка: список команд, код выхода 0
llm ask "Столица Франции?" --routing routing.json
llm ask "Привет" -m "Deep Sec" -m opencode-go   # цепочка из CLI, если в routing нет chain
llm json "Разбери запрос" --schema schema.json   # в stdout только JSON-объект
llm render --template prompt.md --vars vars.json # шаблон mustache; нет переменной — код 2
llm models --json                        # провайдеры routing, источник ключа, цепочка
llm routing validate routing.json        # проверка перед сохранением; ROUTING_INVALID с путём к полю
llm routing import config.toml           # перенос config.toml llmkit < 0.8
llm auth status --check --json           # ключ шлюза: откуда и работает ли; 3 — ключ не принят
llm cost --since 7d --json               # расходы из журнала шлюза, по ключам
llm config show --json                   # итоговые настройки вызова
llm doctor --json                        # готовность: версия, конфиг, routing, шлюз
llm describe --json                      # контракт CLI документом OpenCLI
```

### Поверхность шлюза

Одна команда — один эндпоинт шлюза; ответ типизирован в `--json`, форматы
провайдера llmkit не разбирает.

```bash
llm image generate "кот в шляпе" -m openai/gpt-image-1 --out cat.png --json
llm audio speech "привет" -m openai/gpt-4o-mini-tts --voice alloy --out speech.mp3 --json
llm audio transcribe speech.mp3 -m openai/whisper-1 --json
llm audio voices --json
llm video generate "волна на пляже" -m google/veo-3 --json
llm video get video_1 --json
llm embeddings create "текст" -m openai/text-embedding-3-small --json
llm web search "llmkit" -m perplexity/sonar --json
llm web fetch https://example.com --json
llm model list --json
llm model show deepseek/deepseek-v4.1-flash-1017 --json
llm chat responses "Столица Франции?" -m openai/gpt-5 --json
llm chat messages "Столица Франции?" -m anthropic/claude-x --json
```

Картинка и речь приходят байтами — их место в файле `--out`; ссылку или URL
`--json` отдаёт в поле `url`.

## Как агент работает с CLI

1. `llm --help` и `llm <команда> --help` — справка из кода: у каждой команды есть
   строка `Example:`, у каждого флага `help=`.
2. `--json` — машинный конверт в stdout: `{"ok": true, ...}` или
   `{"ok": false, "error": {"code", "message", "action"}}`.
3. Коды выхода говорят, что делать: 0 — готово, 2 — аргументы, 3 — ключ, 5 — шлюз.
4. `llm doctor --json` — готовность до работы; `llm describe --json` — контракт
   CLI для каталога инструментов.

## Расходы

`llm cost` читает SQLite шлюза: `LLMKIT_GATEWAY_DB`, по умолчанию
`~/.9router/db/data.sqlite`. Файл открывается только на чтение — llmkit его не
пишет. Строки отчёта — по ключу шлюза (`apiKey`); потребителя различает его
собственный ключ. Период: `7d`, `12h`, `2w`, `ГГГГ-ММ-ДД` или метка ISO 8601. Нет файла — код 5,
`GATEWAY_DB_UNAVAILABLE` с путём.

## Python API

```python
import asyncio
from llmkit import LlmKit, Task

kit = LlmKit(routing=routing)  # routing — dict по схеме v1


async def main():
    print(await kit.generate("Одним словом: столица Франции?", system="Отвечай кратко"))


asyncio.run(main())
```

`LlmKit.ask` возвращает `Answer`: `data`, `model` (запрошенная строка),
`served_model` (что назвал шлюз), `provider`, `cost_usd`, `attempts`, токены,
`latency_ms`, `warnings`, `ok`. `ask_many` идёт параллельно (`concurrency`) и не
рвёт пачку на упавшей задаче; `default` у `Task` — что вернуть, когда моделей нет.
Синхронные обёртки — `ask_sync`, `generate_sync`, `ask_many_sync`.

## Решения

[docs/adr/](docs/adr/). Действующее: ADR-0001 — llmkit надстройка над шлюзом
9router, своего состояния и доступа к провайдерам нет.

## Разработка

Команды разработки (`uv sync`, гейт `gate check` на этой машине — команда
`[publish] gate_command` в `.agents/antagor/antagor.toml`)
и порядок релиза — в [AGENTS.md](AGENTS.md).

```bash
uv run llm --help                # CLI из исходников
```
