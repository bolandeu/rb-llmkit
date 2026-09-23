# llmkit — спецификация v1

Общий LLM-слой для инструментов пользователя: одна библиотека, поверх неё тонкие
оболочки — CLI, локальный HTTP-прокси, скилл для Claude Code. Заменяет шесть
самописных клиентов (antagor, intentree, windmill, tasks/intent, content-optimizer).

Статус: спецификация согласована 2026-09-21. Реализация по фазам (раздел 12).

## 1. Решения и отвергнутые альтернативы

| Задача | Решение | Отвергнуто и почему |
|---|---|---|
| Провайдеры, вызов моделей, стоимость | **LiteLLM** (MIT, pin `==1.102.0`) | aisuite — заброшен с 12.2024; any-llm — нет фолбэков и учёта; pydantic-ai — агентный фреймворк, тяжелее задачи |
| JSON по pydantic-схеме, ретрай при невалидном ответе | **Instructor** (`instructor.from_litellm`) | своя валидация — уже написана трижды, не нужна |
| Кэш ответов | своя таблица SQLite (~60 строк) | кэш LiteLLM (diskcache): не даёт учесть попадание с нашими метками, ключ непрозрачен, отдельный файл-формат |
| Ключи | `keyring` (связка macOS) + env | .env-файлы — запрещены конвенцией cli-builder |
| Конфиг | TOML через `platformdirs`, pydantic-модели | — |
| CLI | Typer + rich, конвенции cli-builder (`--json`, exit-коды, stderr для диагностики) | — |
| Прокси | свой FastAPI-сервер поверх ядра (extra `[serve]`) | LiteLLM Proxy: тяжёлые зависимости, наш учёт по меткам и уровни мимо него не проходят |

Риски LiteLLM: медленный импорт (~1 с) — импортировать лениво, только в пути вызова;
инцидент с бэкдором в 1.82.7/1.82.8 — версия пинится точно, перед пином проверить
advisory на PyPI/GitHub.

## 2. Пакет

- Имя пакета и импорта `llmkit`, CLI-команда `llm`. Репозиторий `github.com/bolandeu/llmkit`,
  установка в потребители через `[tool.uv.sources] llmkit = { git = ... }`.
- Python >= 3.11, `uv`, `hatchling`, `src/llmkit/`. Тесты `pytest` + `pytest-asyncio`.
- Зависимости: `litellm==1.102.0`, `instructor>=1.17`, `pydantic>=2`, `keyring>=25`,
  `platformdirs>=4`, `typer>=0.12`, `rich>=13`, `tomli-w>=1`.
  Extra `serve`: `fastapi`, `uvicorn`.
- Структура:

```
src/llmkit/
  __init__.py      # экспорт: LlmKit, Task, Answer, Attempt, Stats, Config, load_config, errors
  config.py        # модели конфига, загрузка, слияние
  keys.py          # резолв ключей: аргумент → env → keychain
  providers.py     # описание провайдера → аргументы litellm
  chain.py         # цепочки, классификация ошибок, политика ретраев
  cache.py         # SQLite-кэш ответов
  usage.py         # SQLite-журнал вызовов, бюджеты, отчёты
  core.py          # LlmKit: ask / generate / ask_many + sync-обёртки
  errors.py
  _sync.py         # запуск корутины из синхронного кода
  cli/             # фаза 2
  serve/           # фаза 4
```

## 3. Конфиг

Порядок слияния (позже перекрывает раньше): дефолты в коде → `~/.config/llmkit/config.toml`
(`platformdirs.user_config_dir("llmkit")`) → `.llmkit/config.toml` в проекте (поиск вверх
от cwd) → env `LLMKIT_*` (только для скалярных полей: `LLMKIT_CONFIG` путь к файлу,
`LLMKIT_CACHE=0`, `LLMKIT_LOG_LEVEL`) → аргументы `LlmKit(...)`.
Заданный `LLMKIT_CONFIG` **заменяет** поиск файлов: читается только он.

```toml
[providers.openrouter]
kind = "openrouter"                 # openrouter | openai | anthropic | gemini | ollama | openai_compatible
# ключ: env OPENROUTER_API_KEY или keychain llmkit:openrouter

[providers.ollama]
kind = "ollama"
base_url = "https://ollama.com"     # локальный: http://localhost:11434
[providers.ollama.prices]           # $/1M токенов, если LiteLLM цену не знает
"gpt-oss:120b" = { input = 0.15, output = 0.60 }

[providers.deepseek]
kind = "openai_compatible"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"

[levels]                            # уровень = цепочка "provider/model" по порядку;
                                    # модели ниже — пример, набор выбирает пользователь
cheap  = ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"]
judge  = ["openrouter/anthropic/claude-sonnet-4", "openrouter/openai/gpt-4o"]
strong = ["openrouter/anthropic/claude-opus-4"]

[defaults]
level = "cheap"
temperature = 0.0
timeout = 120                       # секунд на один HTTP-вызов
max_tokens = 4096
concurrency = 6                     # параллельных вызовов в ask_many

[cache]
enabled = true
ttl_days = 30
path = "~/.cache/llmkit/cache.sqlite"        # platformdirs user_cache_dir по умолчанию

[usage]
path = "~/.local/share/llmkit/usage.sqlite"  # platformdirs user_data_dir по умолчанию

[budget]                            # только предупреждения, ничего не прерывает
daily_usd = 20.0                    # дефолт в коде
[budget.tags]                       # лимит на значение метки, ключ "метка=значение"
"tool=intentree" = 2.0
"niche=ved" = 1.0

[retry]                             # по типам ошибок, см. раздел 6
timeout = 1
rate_limit = 2
server = 2
invalid_output = 2
```

Модель-ссылка: строка `provider/model`, где `provider` — ключ из `[providers]`, всё после
первого `/` — имя модели у провайдера (у OpenRouter само содержит `/`).

Отображение на LiteLLM (`providers.py`):

| kind | model для litellm | доп. аргументы |
|---|---|---|
| openrouter | `openrouter/<model>` | `api_key` |
| openai | `<model>` | `api_key` |
| anthropic | `anthropic/<model>` | `api_key` |
| gemini | `gemini/<model>` | `api_key` |
| ollama | `ollama_chat/<model>` | `api_base`, `api_key` (Ollama Cloud требует Bearer). **Фаза 0 проверяет**; если `ollama_chat/` с ollama.com не работает — использовать `openai/<model>` + `api_base=<base_url>/v1` |
| openai_compatible | `openai/<model>` | `api_base`, `api_key` |

Стандартные env-имена ключей по kind: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_API_KEY`; `api_key_env` в конфиге перекрывает.

## 4. Ключи (`keys.py`)

Порядок: явный `api_key` в конфиге провайдера (не рекомендуется) → env → keychain.
Keychain: `keyring.get_password("llmkit:<provider>", "<provider>")`, значение — JSON
`{"api_key": "..."}` (та же форма, что `credentials/manager.py` из cli-builder, чтобы
CLI `llm keys` и другие инструменты пользователя работали одинаково). Недоступная
связка (headless Linux) — предупреждение в лог и только env. Нет ключа нигде →
`KeyMissing(provider)` с подсказкой: `llm keys set <provider>` или `export <ENV>`.
Библиотека ключи только читает; `keys.store(provider, api_key)` есть в модуле, но
вызывает её только CLI.

Ключи для провайдеров без аутентификации (локальный Ollama) — не обязательны:
`requires_key = false` в конфиге провайдера.

## 5. Публичный API (`core.py`)

```python
from llmkit import LlmKit, Task, Answer

kit = LlmKit()                       # конфиг по разделу 3; LlmKit(config=Config(...)) для явного
kit = LlmKit(tags={"tool": "intentree"})   # метки по умолчанию на все вызовы

@dataclass(frozen=True)
class Task:
    user: str | None = None                  # либо user (+system), либо messages
    system: str | None = None
    messages: list[dict] | None = None       # OpenAI-формат, если нужен диалог
    schema: type[BaseModel] | dict | None = None   # pydantic-класс или JSON Schema; None = текст
    level: str | None = None                 # имя уровня из конфига; None = defaults.level
    chain: list[str] | None = None           # явная цепочка "provider/model", перекрывает level
    tags: dict[str, str] = field(default_factory=dict)  # tool/task/niche/... — любые
    default: Any = None                      # что вернуть, если все модели упали
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    cache: bool | None = None                # None = из конфига
    retry: bool = True                       # False = 0 повторов на сбойной модели, сразу следующая
    id: str | None = None                    # свой идентификатор, попадает в usage и on_progress

@dataclass
class Attempt:
    model: str; provider: str; error_type: str | None; error: str | None
    latency_ms: int; prompt_tokens: int; completion_tokens: int; cost_usd: float

@dataclass
class Answer:
    data: Any                   # экземпляр schema | dict (если schema — dict) | str (текст) | default
    source: str                 # "llm" | "cache" | "default"
    model: str = ""             # "provider/model", которая ответила
    provider: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True
    latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)   # бюджет, неизвестная цена
    error: str | None = None    # заполнен, если source == "default"
    task_id: str | None = None
    @property
    def ok(self) -> bool: return self.source in ("llm", "cache")

# --- async (основной) ---
async def ask(self, task: Task) -> Answer
    # все модели упали и default is None → raise AllModelsFailed(attempts)
async def generate(self, prompt: str, *, system: str | None = None,
                   level: str | None = None, **task_kw) -> str | None
    # строковый путь под antagor/content-optimizer: ошибки НЕ бросает, возвращает None и пишет в лог
async def ask_many(self, tasks: Sequence[Task], *, concurrency: int | None = None,
                   on_progress: Callable[[int, int, Answer], None] | None = None,
                   raise_on_error: bool = False) -> list[Answer]
    # порядок результатов = порядок задач; упавшая задача → Answer(source="default", error=...)
    # даже без default (data=None), чтобы пачка не рвалась; raise_on_error=True — бросать AllModelsFailed
    # семафор concurrency; кэш делает возобновление после сбоя бесплатным
# --- sync-обёртки ---
def ask_sync(self, task) -> Answer
def generate_sync(self, prompt, **kw) -> str | None
def ask_many_sync(self, tasks, **kw) -> list[Answer]
# --- прочее ---
@property
def stats(self) -> Stats     # за время жизни экземпляра: calls, cached, failed, fallbacks,
                             # prompt_tokens, completion_tokens, cost_usd, seconds, by_model: Counter
async def aclose(self) / def close(self)
```

`_sync.py`: если event loop уже запущен в этом потоке — выполнить корутину в отдельном
потоке со своим loop; иначе `asyncio.run`. Для intentree с `ThreadPoolExecutor` это
безопасно.

Тестируемость: `LlmKit(completion=<async callable>)` подменяет функцию вызова модели
(сигнатура как у `litellm.acompletion`); тесты не ходят в сеть.

## 6. Цепочки и ошибки (`chain.py`)

Классификация исключений LiteLLM/Instructor в тип ошибки:

| error_type | Источник | Действие по умолчанию |
|---|---|---|
| `timeout` | `litellm.Timeout` | ретрай `retry.timeout` раз на той же модели, затем следующая |
| `rate_limit` | `litellm.RateLimitError` | ретрай `retry.rate_limit` раз с backoff (Retry-After если есть, иначе 2·2ⁿ с, макс 30), затем следующая |
| `server` | `ServiceUnavailableError`, `InternalServerError`, `APIConnectionError` | ретрай `retry.server` раз с backoff, затем следующая |
| `invalid_output` | `InstructorRetryException` (Instructor уже сделал `max_retries=retry.invalid_output`) / пустой ответ | следующая модель |
| `refusal` | `ContentPolicyViolationError`, finish_reason `content_filter` | следующая модель |
| `context_length` | `ContextWindowExceededError` | следующая модель |
| `auth` | `AuthenticationError`, `KeyMissing` | следующая модель, лог уровня ERROR |
| `bad_request` | `BadRequestError`, прочие `APIError` | следующая модель |

Цепочка: `task.chain` → иначе `levels[task.level]` → иначе `levels[defaults.level]`.
Каждая попытка пишется в `Answer.attempts` и в usage (раздел 8). Все шаги исчерпаны →
`AllModelsFailed` или `default`. Переход на следующую модель после первой считается
фолбэком (`stats.fallbacks`).

Структурированный вывод: `instructor.from_litellm(litellm.acompletion, mode=...)`;
режим `JSON` для ollama/openai_compatible, `TOOLS` для openrouter/openai/anthropic/gemini
(перекрывается `mode` в конфиге провайдера). Если `schema` — dict (готовая JSON Schema),
Instructor не используется: вызов идёт с `response_format={"type":"json_schema",
"json_schema":{"name":"answer","schema":<dict>,"strict":true}}`, ответ парсится `json.loads`,
ошибка парсинга → `invalid_output` с `retry.invalid_output` повторами на той же модели.
Валидация по dict-схеме остаётся на стороне потребителя (intentree это уже делает);
новых зависимостей вроде `jsonschema` не добавлять.

## 7. Кэш (`cache.py`)

SQLite, таблица `cache(key TEXT PRIMARY KEY, model TEXT, created_at REAL, response TEXT)`.
`key = sha256(canonical_json({model, api_base, messages, schema, temperature, max_tokens}))`,
где `model` — ссылка `provider/model` конкретной попытки (не уровень и не имя модели для
LiteLLM): ответ дешёвой модели не выдаётся за ответ сильной, а одна и та же модель у
ollama.com и у localhost не делит запись. Ключ провайдера в подпись не входит.
Кэш проверяется по **всей цепочке** до первого сетевого вызова и до резолва ключей:
попадание на любой модели цепочки отдаётся сразу, без обращения к провайдерам.
TTL из конфига; протухшие записи удаляются при старте (`DELETE WHERE created_at < …`).
`journal_mode=WAL`, `busy_timeout=5000` — несколько процессов одновременно.
Попадание пишется в usage как `status="cache"`, стоимость 0.

## 8. Учёт и бюджет (`usage.py`)

SQLite `usage.sqlite`, `journal_mode=WAL`. Таблица `calls`:

```
id INTEGER PK, ts REAL, task_id TEXT, tags TEXT (JSON), level TEXT,
model TEXT, provider TEXT, status TEXT ('ok'|'cache'|'failed'),
error_type TEXT, attempt INTEGER, prompt_tokens INT, completion_tokens INT,
cost_usd REAL, cost_known INT, latency_ms INT, pid INT
```
Одна строка на попытку. Индексы: `ts`, `status`. Отчёты через `json_extract(tags, '$.tool')`.

API:
```python
usage.report(group_by=("tool","niche"), since=datetime|"7d"|None, until=None) -> list[Row]
# Row: keys (dict метка→значение), calls, cached, failed, prompt_tokens, completion_tokens, cost_usd
usage.total(since) -> Row
```

Стоимость: `litellm.completion_cost(response)`; если LiteLLM цену не знает —
`providers.<p>.prices[model]`; если и там нет — `cost_usd=0, cost_known=False`, одно
предупреждение на модель за процесс.

Бюджет: перед каждым сетевым вызовом сумма `cost_usd` за сегодня (UTC) по `daily_usd` и по
каждому `budget.tags` ключу, чей `метка=значение` совпадает с метками задачи. Превышение →
`logging.warning` один раз на бюджет за процесс + строка в `Answer.warnings`. Работа не
прерывается и уровень не понижается (решение пользователя).

## 9. Логирование

`logging.getLogger("llmkit.*")`. Одна строка INFO на вызов: модель, статус, токены, стоимость,
латентность, метки. DEBUG — попытки и причины фолбэка. Шум LiteLLM глушится:
`litellm.suppress_debug_info = True`, логгер `LiteLLM` на WARNING. Ключи в лог не попадают.

## 10. CLI `llm` (фаза 2)

По конвенциям cli-builder: `--json` у всех команд, диагностика в stderr, коды выхода
как в `reference/conventions.md`: 0 — успех, 1 — непредвиденная ошибка, 2 — неверные
аргументы (и `llm serve` до фазы 4), 3 — нет ключа (`AUTH_REQUIRED`), 5 — все модели
цепочки упали (`PROVIDER_ERROR`).

| Команда | Что делает |
|---|---|
| `llm ask "текст" [--level L] [--model p/m] [--system S] [--tag k=v ...] [--no-cache]` | текстовый ответ |
| `llm json "текст" --schema schema.json [те же флаги]` | JSON по схеме, вывод только JSON |
| `llm keys set <provider>` (ввод скрыт) / `llm keys status` / `llm keys rm <provider>` | связка ключей |
| `llm models` | провайдеры, уровни, цепочки, есть ли ключ |
| `llm cost [--by tool,niche] [--since 7d]` | отчёт из usage, таблица rich или JSON |
| `llm config path` / `show` / `init` | конфиг; `init` пишет шаблон из раздела 3 |
| `llm serve [--port 8765]` | фаза 4 |

## 11. Прокси `llm serve` (фаза 4)

FastAPI, extra `[serve]`. `POST /v1/chat/completions` (OpenAI-формат, без stream в v1):
`model` — имя уровня или `provider/model`; `response_format json_schema` → schema;
заголовок `X-LlmKit-Tags: tool=windmill,task=extract` → метки. `GET /v1/models` — уровни и
модели из конфига. Слушает только `127.0.0.1`. Ответ — OpenAI-совместимый объект с `usage`.
Запуск как сервис — `launchd` plist в README.

## 12. Фазы и критерии готовности

| Фаза | Содержание | Готово, когда |
|---|---|---|
| 0 | `scripts/smoke.py`: 3 вызова через LiteLLM — OpenRouter текст, OpenRouter JSON через Instructor, Ollama Cloud текст (`ollama_chat/` и, если не работает, `openai/`+`/v1`) | скрипт печатает ответы, токены и cost; вывод записан в `docs/smoke-2026-09.md`, выбранный путь для Ollama зафиксирован в разделе 3 |
| 1 | Ядро: разделы 2–9, тесты на фейковом `completion` (цепочка по каждому типу ошибки, кэш-попадание, usage-строки, бюджетное предупреждение, sync-обёртки из работающего loop, ask_many порядок и concurrency), README | `uv run pytest` зелёный, `uv run python -c "import llmkit"` < 0.3 с (litellm лениво) |
| 2 | CLI по разделу 10 | тесты на `CliRunner`, `llm --help`/`llm cost --json` работают на пустой базе |
| 3 | Перевод intentree: адаптер `Task(stage, subject_type, subject_id, …)` → `llmkit.Task(tags={tool:"intentree", stage, subject_type, niche})`, `LlmRunner` поверх `ask_many_sync`, `LlmStats` из `kit.stats`; журнал решений остаётся в intentree | тесты intentree зелёные, `providers/llm.py` и кэш-таблица `llm_cache` удалены |
| 4 | Прокси (раздел 11) + скилл Claude Code, вызывающий `llm ... --json` | `curl` к прокси возвращает ответ, вызов виден в `llm cost` |

Вне v1: streaming, embeddings (`levels.embed`), батч-API провайдеров, веб-панель.
