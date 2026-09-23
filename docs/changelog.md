# Changelog

Обратный хронологический порядок, группировка по фазам (см. PRD.md §12).
Планы и отложенное — в BACKLOG.md.

## 2026-09-23

- **Подписки вместо API-ключей**: `kind = "chatgpt"` (OAuth Codex CLI, Responses
  API `chatgpt.com/backend-api/codex`) и `kind = "claude_cli"` (установленный
  `claude -p`). Порт решений iva-agent на Python: файл токенов 0600, обновление
  под замком с перечитыванием файла, повтор при 401, защита `account_id`;
  чистое окружение и убийство группы процессов у CLI. JSON по схеме нативно,
  стоимость 0. Команды `llm auth login|status|logout`, провайдеры `chatgpt` и
  `claude` во встроенных дефолтах. Claude проверен живым вызовом.
- **CLI**: `llm ask`/`llm json` получили флаг `--timeout` (переопределяет
  `defaults.timeout` на конкретный вызов, как уже работали `--temperature`
  и `--max-tokens`).
- **`Task.retry`** (новое поле, по умолчанию `True`) и флаг CLI `--no-retry`:
  `False` — ноль повторов на сбойной модели для этого вызова, сразу
  следующая в цепочке (включая ретраи Instructor на невалидном выводе).
  Тонкая настройка счётчиков `[retry]` по-прежнему только в конфиге —
  осознанно не стали городить per-call переопределение всех 4 категорий.

## 2026-09-21

- **Фаза 2 — CLI `llm`**: команды `ask`, `json`, `keys`, `models`, `cost`,
  `config`, заглушка `serve`. Тесты на `CliRunner`. (143a759)
- **Правки по ревью**: исправления в `core.py`, коды выхода CLI приведены к
  конвенциям cli-builder. (af4c72a)
- **Задание фазы 3**: подготовлен план перевода antagor на llmkit,
  `docs/phase3-antagor.md`. (4443943)
- **Фазы 0–1 — ядро**: `config`, `keys`, `providers`, `chain`, `cache`,
  `usage`, `core`. 137 тестов без сети, импорт `llmkit` ~80 мс, smoke-тест на
  реальных ключах (`docs/smoke-2026-09.md`), подтверждена работа Ollama Cloud
  через `ollama_chat/` + `api_base=https://ollama.com`. (abc006c)
