# llmkit — инструкция для агента

Библиотека-слой над LLM-провайдерами: цепочки моделей, кэш, учёт расходов.
Пакетный менеджер — `uv` (не pip/poetry). Дистрибутив — `rb-llmkit`
(`[project] name`, по нему `importlib.metadata.version` — `health.DIST_NAME`),
импорт-пакет — `llmkit`, команда — `llm`.

- Спецификация — `docs/prd.md`, она главнее этого файла.
- Планы — `docs/backlog.md`, сделанное — `CHANGELOG.md` (собирается из `changelog.d/`).

## Команды

```bash
uv sync                              # после переименования в rb-llmkit один раз: uv sync --reinstall-package rb-llmkit
uv run scripts/release.py --check   # весь гейт: lock, ruff, ty, pytest, фрагмент, сборка колеса — перед каждым коммитом
uv run pytest -q                    # только тесты
uv run python -X importtime -c "import llmkit" 2>&1 | tail -1   # должно быть < 300 мс
```

## Версии, changelog, справка

Стандарт — `~/Projects/tools/docs/standard-release.md`.

- Версия только из git-тега `vX.Y.Z`, строки `version =` в `pyproject.toml` нет.
  Релиз — `uv run scripts/release.py patch|minor|major` с чистого `main`; push
  только с подтверждения пользователя. SemVer на `0.x`: исправление или
  совместимая функция — patch, ломающее (Python API, команды, флаги, форма
  `--json`, коды выхода и ошибок) — minor.
- `CHANGELOG.md` руками не правится: на каждое заметное изменение —
  `uv run towncrier create +<slug>.<type>.md -c "..."` (types: added, changed,
  deprecated, removed, fixed, security; в slug без точек).
- Докстринг команды — её `--help`: поменял поведение команды — поправь
  докстринг в том же коммите (строка `Example: llm ...` обязательна, у каждого
  параметра `help=`), затем `uv run pytest --snapshot-update` и просмотри
  `tests/snapshots/help/`. Это проверяют хуки (`.claude/settings.json`,
  `.githooks/pre-commit`, подключение — `scripts/install_hooks.sh`) и тесты.
- `llm auth status [--check] --json` — общий контракт инструментов (§8),
  форму фиксирует `tests/test_health.py`; реализация — `src/llmkit/health.py`.
- `scripts/release.py` — копия из cli-generator, не править; единственное
  местное отличие шаблонных скриптов — поиск команд в
  `scripts/check_command_docstrings.py` (`src/*/cli/*.py`, `with guard(ctx):`).

## Конвенции

- Комментарии и докстринги — по-русски, короткие.
- [docs/architecture.md](docs/architecture.md) — структура модулей, ленивые
  импорты, классификация ошибок, ключи, зависимости.
- [docs/testing.md](docs/testing.md) — как писать тесты (без сети).
- [docs/cli-conventions.md](docs/cli-conventions.md) — паттерн CLI-команд,
  коды выхода.
