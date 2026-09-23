# Архитектура llmkit

## Структура модулей

```
src/llmkit/
  config.py     модели конфига, загрузка и слияние слоёв
  keys.py       ключи: конфиг → env → связка ключей ОС
  providers.py  провайдер + модель → аргументы LiteLLM
  chain.py      цепочки, классификация ошибок, ретраи и backoff
  cache.py      SQLite-кэш ответов
  usage.py      SQLite-журнал вызовов, отчёты, бюджеты
  core.py       LlmKit: ask / generate / ask_many и sync-обёртки
  errors.py     исключения
  _sync.py      запуск корутины из синхронного кода
  transports/   провайдеры по подписке: свой acompletion вместо LiteLLM
    _common.py      ошибки Subscription* и сборка litellm.ModelResponse
    chatgpt_auth.py вход OAuth Codex, файл токенов, обновление под замком
    chatgpt.py      Responses API chatgpt.com/backend-api/codex, SSE
    claude_cli.py   вызов `claude -p`, чистое окружение, kill группы процессов
  cli/          команда `llm` — см. cli-conventions.md
scripts/smoke.py  реальные вызовы провайдеров (фаза 0)
```

## Ленивые импорты

`litellm`, `instructor` и `keyring` импортируются лениво, внутри функций
пути вызова: `import llmkit` обязан оставаться быстрым (порог — 300 мс,
проверка — команда в корневом AGENTS.md).

## Провайдеры по подписке

`providers.build` для `kind` из `SUBSCRIPTION_KINDS` проверяет вход (файл
токенов / наличие CLI) и кладёт в `ModelCall.completion` функцию транспорта;
ядро зовёт её вместо `litellm.acompletion`. Подмена `LlmKit(completion=...)`
по-прежнему перекрывает всё — тесты сети не касаются.

## Классификация ошибок

Идёт по **имени класса** исключения (`chain.py`), чтобы модуль не тянул
litellm на импорте. `classify()` возвращает `None` для чужих исключений —
их ядро пробрасывает, а не маскирует под ошибку провайдера.

## Ключи

Не логируются и не пишутся на диск библиотекой; `.env`-файлы не используются.

## Стиль

Ruff: `line-length = 120`, набор правил — в `pyproject.toml`.

## Зависимости

Сверх раздела 2 `docs/prd.md` не добавлять.
