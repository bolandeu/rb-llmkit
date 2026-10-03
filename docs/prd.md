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
| Подписка ChatGPT (без API-ключа) | свой транспорт `transports/chatgpt*.py` на `httpx` — порт iva-agent (github.com/smixs/iva-agent), сверен с Hermes | провайдер `chatgpt/` LiteLLM: подмешивает системный промпт «You are Codex…», при сбое обновления токена запускает интерактивный вход посреди вызова, нет повтора при 401 и защиты `account_id`; прокси openai-oauth — лишний процесс |
| Подписка Claude (без API-ключа) | вызов установленного `claude -p` (`transports/claude_cli.py`), минимальный порт iva-agent | Claude Agent SDK — ещё зависимость ради того же CLI; прямой вызов Messages API с OAuth-токеном отвечает 429; реле и муляж MCP из iva-agent — нужны агенту, не одному ответу |

Риски LiteLLM: медленный импорт (~1 с) — импортировать лениво, только в пути вызова;
инцидент с бэкдором в 1.82.7/1.82.8 — версия пинится точно, перед пином проверить
advisory на PyPI/GitHub.

## 2. Пакет

- Имя пакета и импорта `llmkit`, CLI-команда `llm`. Репозиторий `github.com/bolandeu/llmkit`,
  установка в потребители через `[tool.uv.sources] rb-llmkit = { git = ..., tag = ... }` (дистрибутив `rb-llmkit`, импорт `llmkit`).
- Python >= 3.11, `uv`, `hatchling`, `src/llmkit/`. Тесты `pytest` + `pytest-asyncio`.
- Зависимости: `litellm==1.102.0`, `instructor>=1.17`, `pydantic>=2`, `keyring>=25`,
  `platformdirs>=4`, `typer>=0.12`, `rich>=13`, `tomli-w>=1`, `httpx>=0.27` (транспорт
  подписки ChatGPT; уже приходит с LiteLLM, указан явно), `sqlalchemy>=2.0`, `alembic>=1.14`,
  `psycopg[binary]>=3.2` (журнал расходов в общей PostgreSQL, слой БД шаблона cli-generator).
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
  usage.py         # журнал вызовов (llmkit_calls), бюджеты, отчёты
  db/              # слой БД: PostgreSQL или SQLite, миграции Alembic
  core.py          # LlmKit: ask / generate / ask_many + sync-обёртки
  errors.py
  _sync.py         # запуск корутины из синхронного кода
  transports/      # провайдеры по подписке: chatgpt_auth, chatgpt, claude_cli
  cli/             # фаза 2
  serve/           # фаза 4
```

## 3. Routing и настройки (с 0.8.0)

Встроенных провайдеров и уровней нет; `config.toml` не читается (решение dev и
пользователя 2026-10-02, T86). Провайдеры, цепочка и цены приходят **данными** —
routing v1, публичный контракт: `src/llmkit/contracts/routing-v1.schema.json` и
векторы `routing-v1.vectors.json` (валидные и невалидные routing → ожидаемый
`error.path`). Секретов в routing нет — только имена переменных с ключами.

```json
{
  "version": 1,
  "providers": {
    "openrouter": {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"},
    "ollama": {"protocol": "ollama", "base_url": "https://ollama.com"},
    "deepseek": {"protocol": "openai_compatible", "base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY"},
    "chatgpt": {"protocol": "chatgpt"}
  },
  "chain": ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"],
  "prices": {"ollama/gpt-oss:120b": {"input": 0.15, "output": 0.60}}
}
```

- `protocol` — таблица ниже; `base_url` обязателен для ollama и openai_compatible;
  `mode` — режим Instructor (TOOLS | JSON | JSON_SCHEMA | MD_JSON).
- `chain` — цепочка «провайдер/модель»; обязательна для вызова, если цепочка не
  пришла иначе (`-m …` в CLI, `Task.chain` в библиотеке). `-m` вместе с
  `routing.chain` — `ROUTING_INVALID` «chain задана дважды».
- `prices` — $ за 1M токенов по «провайдер/модель»; главнее справочника LiteLLM.
- Ошибка схемы — `RoutingInvalid` / `ROUTING_INVALID` (код 2) с `path` — JSON
  Pointer поля; нет routing — `RoutingMissing` / `ROUTING_MISSING` (код 2).
- Передача в CLI: `--routing '<json>'` или `--routing <файл>`, **не stdin** (stdin —
  текст или шаблон промпта); без него — `LLMKIT_ROUTING_FILE`; без него —
  `routing.json` в `platformdirs.user_config_dir("llmkit")` (macOS —
  `~/Library/Application Support/llmkit/`, Linux — `~/.config/llmkit/`; права шире
  600 — предупреждение); нет ничего — `ROUTING_MISSING` с путём по умолчанию.
  Библиотека env и файл по умолчанию не читает: `LlmKit(routing=dict)`; без routing первый вызов
  бросает `RoutingMissing`.
- Ключ: `key_env`, по умолчанию `LLM_<ПРОВАЙДЕР>_API_KEY` (верхний регистр, не
  буквы и не цифры → `_`) → старое имя (`OPENROUTER_API_KEY`, `CCODE_API_KEY`,
  `ANYMODEL_API_KEY`, `OLLAMA_API_KEY`…; один цикл, предупреждение «rename to
  LLM_…») → связка ключей `llmkit:<провайдер>` → `KeyMissing` / `AUTH_MISSING`
  (код 3, `error.variable`). Значение ключа не печатается и не пишется в учёт.
- Перенос старого конфига: `llm routing import <config.toml>` — провайдеры (вместе
  со встроенными дефолтами 0.7) и цены в routing, уровни — отдельно (`levels`).

Настройки вызовов (не routing): дефолты в коде → env `LLMKIT_CACHE=0`,
`LLMKIT_LOG_LEVEL` → аргументы `LlmKit(...)` / флаги CLI.

| настройка | дефолт |
|---|---|
| temperature / timeout / max_tokens / concurrency | 0.0 / 120 с / 16000 / 6 |
| cache | включён, ttl 30 дней, `platformdirs.user_cache_dir/cache.sqlite` |
| usage | `platformdirs.user_data_dir/usage.sqlite` (или `LLMKIT_DATABASE_URL`) |
| budget.daily_usd | 20.0 — только предупреждение |
| retry | timeout 0, rate_limit 6, server 6, invalid_output 2 (раздел 6) |

Модель-ссылка: строка `provider/model`, где `provider` — ключ из `routing.providers`, всё после
первого `/` — имя модели у провайдера (у OpenRouter само содержит `/`).

Отображение на LiteLLM (`providers.py`):

| protocol | model для litellm | доп. аргументы |
|---|---|---|
| openrouter | `openrouter/<model>` | `api_key` |
| openai | `<model>` | `api_key` |
| anthropic | `anthropic/<model>` | `api_key` |
| gemini | `gemini/<model>` | `api_key` |
| ollama | `ollama_chat/<model>` | `api_base`, `api_key` (Ollama Cloud требует Bearer). **Фаза 0 проверяет**; если `ollama_chat/` с ollama.com не работает — использовать `openai/<model>` + `api_base=<base_url>/v1` |
| openai_compatible | `openai/<model>` | `api_base`, `api_key` |
| chatgpt | не LiteLLM: `transports/chatgpt.acompletion` | вход `llm auth login <провайдер>`, файл токенов 0600; ключ не нужен |
| claude_cli | не LiteLLM: `transports/claude_cli.acompletion` | вход держит Claude Code CLI; `CLAUDE_COMMAND` — другой бинарь |

Модели решений (`LlmKit.decide`, раздел 5) — не LiteLLM: `transports/decisions.adecide`,
POST на `https://openrouter.ai/api/alpha/decisions` с ключом провайдера `kind = "openrouter"`.

Провайдеры по подписке: режим Instructor `JSON_SCHEMA` (схема уходит нативно),
стоимость вызова 0 и `cost_known = true`, нет входа — `LoginMissing` (подкласс
`KeyMissing`, тип ошибки `auth`, код выхода CLI 3).

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

kit = LlmKit(routing=routing)        # routing v1 (раздел 3) — dict или Routing; без него первый вызов → RoutingMissing
kit = LlmKit(routing=routing, tags={"tool": "intentree"})   # метки по умолчанию на все вызовы

@dataclass(frozen=True)
class Task:
    user: str | None = None                  # либо user (+system), либо messages
    system: str | None = None
    messages: list[dict] | None = None       # OpenAI-формат, если нужен диалог
    schema: type[BaseModel] | dict | None = None   # pydantic-класс или JSON Schema; None = текст
    chain: list[str] | None = None           # цепочка "provider/model" вместо routing.chain; провайдеры — из routing
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
    cost_usd: float | None = 0.0   # None — цену не знает ни routing, ни LiteLLM
    cost_source: str = "routing"   # routing | litellm | provider | subscription | cache | unknown
    latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)   # бюджет, "price unknown for <model>", "rename to LLM_…"
    error: str | None = None    # заполнен, если source == "default"
    task_id: str | None = None
    served_model: str = ""      # версия, которую назвал провайдер; не назвал — model
    chain_position: int = 0     # 0-based номер ответившей модели
    @property
    def ok(self) -> bool: return self.source in ("llm", "cache")
    cache_hit: bool (property); cost_known: bool (property, cost_source != "unknown")

# --- async (основной) ---
async def ask(self, task: Task) -> Answer
    # все модели упали и default is None → raise AllModelsFailed(attempts)
async def generate(self, prompt: str, *, system: str | None = None, **task_kw) -> str | None
    # строковый путь под antagor/content-optimizer: ошибки НЕ бросает, возвращает None и пишет в лог
async def ask_many(self, tasks: Sequence[Task], *, concurrency: int | None = None,
                   on_progress: Callable[[int, int, Answer], None] | None = None,
                   raise_on_error: bool = False) -> list[Answer]
    # порядок результатов = порядок задач; упавшая задача → Answer(source="default", error=...)
    # даже без default (data=None), чтобы пачка не рвалась; raise_on_error=True — бросать AllModelsFailed
    # семафор concurrency; кэш делает возобновление после сбоя бесплатным
async def decide(self, state: str, questions: dict, **task_kw) -> Answer
    # модели решений OpenRouter: data — словарь answers из ответа как есть
    # (noul — вероятность 0..1; choice/score — с probabilities, confidence);
    # цепочка — routing.chain или chain=, только провайдеры protocol=openrouter (иначе RoutingInvalid);
    # task_kw — chain, tags, default, timeout, retry, id; кэша нет — ответ зависит от состояния;
    # цена — usage.cost ответа (cost_source=provider), иначе routing.prices; served_model — версия за алиасом
# --- sync-обёртки ---
def ask_sync(self, task) -> Answer
def generate_sync(self, prompt, **kw) -> str | None
def ask_many_sync(self, tasks, **kw) -> list[Answer]
def decide_sync(self, state, questions, **kw) -> Answer
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

Цепочка: `task.chain` → иначе `routing.chain` → иначе `RoutingInvalid` (`/chain`).
Каждая попытка пишется в `Answer.attempts` и в usage (раздел 8). Все шаги исчерпаны →
`AllModelsFailed` или `default`. Переход на следующую модель после первой считается
фолбэком (`stats.fallbacks`).

Структурированный вывод: `instructor.from_litellm(litellm.acompletion, mode=...)`;
режим `JSON` для ollama/openai_compatible, `TOOLS` для openrouter/openai/anthropic/gemini
(перекрывается `mode` провайдера в routing). Если `schema` — dict (готовая JSON Schema),
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

База llmkit (`llmkit.db`): общая PostgreSQL, если задан `LLMKIT_DATABASE_URL`, иначе SQLite
`usage.sqlite` (`journal_mode=WAL`). Таблица `llmkit_calls` (до v0.5.0 — `calls`; миграция
0001 переименовывает её в локальной SQLite вместе со строками):

```
id INTEGER PK, ts REAL, task_id TEXT, tags JSON (JSONB в PostgreSQL), level TEXT (с 0.8.0 пуста: уровней нет, метка level — в tags),
model TEXT, provider TEXT, status TEXT ('ok'|'cache'|'failed'),
error_type TEXT, attempt INTEGER, prompt_tokens INT, completion_tokens INT,
cost_usd REAL, cost_known INT, latency_ms INT, pid INT, served_model TEXT
```
`served_model` — версия, которую назвал провайдер (не назвал — элемент цепочки) (нужна за алиасами вида `~…-latest`, чтобы
видеть смену модели); базам до v0.4.2 колонку добавляет миграция 0001.
Одна строка на попытку. Индексы: `ts`, `status`. Отчёты группируются по меткам из `tags`.
Другие инструменты читают представление `llmkit_v1_calls` (без `pid`, `ts` → `called_at`).

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
| `llm ask "текст" [--routing <json\|файл>] [-m p/m ...] [--system S] [--tag k=v ...] [--no-cache]` | текстовый ответ; `--json`: text, task_id (= task_id строки llmkit_calls), model, served_model, chain_position, attempts [{model, error_code}], provider, tokens_in, tokens_out, cost_usd, cost_source, cache_hit, latency_ms, warnings. `--level` удалён (код 2 с подсказкой) |
| `llm json "текст" --schema schema.json [те же флаги]` | JSON по схеме, вывод только JSON; `--json` — как у ask, поле `data` |
| `llm routing validate <файл\|json> [--providers-only]` | проверка routing v1 (Windmill, Directus): ok или `ROUTING_INVALID` с `error.path` |
| `llm routing import <config.toml>` | перенос config.toml < 0.8: routing (providers + prices, key_env по шаблону LLM_<P>_API_KEY, без ключей) и отдельно levels |
| `llm render --template <файл\|текст\|-> [--vars <json-файл\|json>] [--lenient]` | шаблон промпта mustache без экранирования HTML; строго: нет переменной — код 2 (`TEMPLATE_VARIABLE_MISSING`, поле `variable`). Те же `--template/--vars` у ask/json/decide; в метках учёта — `template` и `template_sha256`, без значений переменных |
| `llm keys set <provider>` (ввод скрыт) / `llm keys status` / `llm keys rm <provider>` | связка ключей |
| `llm models [--routing …]` | провайдеры routing, цепочка, источник ключа |
| `llm cost [--by tool,niche] [--since 7d]` | отчёт из usage, таблица rich или JSON |
| `llm config path` / `show` | пути кэша, журнала и routing (LLMKIT_ROUTING_FILE или файл по умолчанию, `routing_default`); итоговые настройки |
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

Вне v1: streaming, embeddings, батч-API провайдеров, веб-панель.

##  13. Правка руками

Routing на машине — `~/Library/Application Support/llmkit/routing.json` (macOS) или
`~/.config/llmkit/routing.json` (Linux), права 600; другой файл — `LLMKIT_ROUTING_FILE`.
Проверка после правки:

```bash
llm routing validate "$(llm config path --json | jq -r .routing_file)" --providers-only
```
