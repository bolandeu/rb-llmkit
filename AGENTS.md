# llmkit — инструкция для агента

Библиотека-слой над LLM-провайдерами: цепочки моделей, кэш, учёт расходов.
Пакетный менеджер — `uv` (не pip/poetry).

- Спецификация — `docs/PRD.md`, она главнее этого файла.
- Планы — `docs/BACKLOG.md`, сделанное — `docs/CHANGELOG.md`.

## Команды

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
uv run python -X importtime -c "import llmkit" 2>&1 | tail -1   # должно быть < 300 мс
```

## Конвенции

- Комментарии и докстринги — по-русски, короткие.
- [docs/architecture.md](docs/architecture.md) — структура модулей, ленивые
  импорты, классификация ошибок, ключи, зависимости.
- [docs/testing.md](docs/testing.md) — как писать тесты (без сети).
- [docs/cli-conventions.md](docs/cli-conventions.md) — паттерн CLI-команд,
  коды выхода.
