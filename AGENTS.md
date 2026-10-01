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

Стандарт — `~/Work/tools/docs/standard-release.md`.

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

## База (журнал расходов)

- Слой БД — `src/llmkit/db/`, перенесён вручную из шаблона cli-generator
  **v1.4.3** (`core/db.py`, `core/tables.py`, `core/normalize.py`, `migrations/`,
  `commands/db.py`, `tests/test_db.py`, `scripts/pg_test.sh`; architecture.md §12). При обновлении
  шаблона сверять с ним эти файлы. Отличия от шаблона:
  - пакет `llmkit/db/` вместо `core/` (`core.py` здесь — модуль `LlmKit`);
    ошибки — в `errors.py` (`DatabaseError` и потомки, библиотечные);
  - локальная SQLite — файл журнала из конфига (`usage.path`, по умолчанию
    `usage.sqlite`), а не `<TOOL>_DB_PATH`; `open_db(path)` принимает его от `Usage`;
  - SQLite мигрируется под `BEGIN IMMEDIATE`: файл одновременно открывают
    несколько процессов (wp-bulk, antagor, `llm`);
  - нет `db push` (расходы с Mac в прод не отправляются) и `doctor`.
- `LLMKIT_DATABASE_URL` → общая PostgreSQL (на homeserver), иначе SQLite. На Mac
  переменной нет — учёт в SQLite. Postgres мигрирует только `llm db upgrade`
  выпущенной версией; каждая миграция совместима с предыдущим релизом
  (expand/contract).
- Таблицы и представления — только `llmkit_*` (`db/tables.py` + миграция руками);
  другие инструменты читают только `llmkit_v1_calls`.
- Кэш ответов (`cache.py`, `cache.sqlite`) — вне слоя БД, локальный `sqlite3`:
  ответы можно получить заново, делить их между машинами незачем (решение пользователя).
- У каждой таблицы — PRIMARY KEY (без него Directus её не покажет); проверяет tests/test_db.py.
- Тесты на PostgreSQL — только через `scripts/pg_test.sh -q tests/test_db.py` (свой
  контейнер, порт от Docker, удаляется после) — никогда не фиксированный порт и
  не чужой сервер.

## Каждое заметное изменение выходит релизом

Серверы, другие инструменты и Mac ставят только по тегам, не из `main`:
влитое без релиза изменение для них не существует. Изменение с фрагментом
changelog закончено только после релиза: влить в `main` →
`uv run scripts/release.py patch|minor|major` → передать релиз корневому
агенту на push (ниже) → назвать новый тег в отчёте. Служебные коммиты
(без фрагмента) ждут следующего релиза. Не оставлять фрагмент на `main` без
релиза, не назвав причину (`~/Work/tools/docs/standard-release.md` §3).

## Инструмент в системе

Инструмент — один из сервисов `~/Work/tools/`: корневой агент его
деплоит, хранит ключи (Doppler) и бэкапит данные (S3). Полные правила —
`~/Work/tools/docs/standard-release.md` §13.

- **Push и вопросы — через корневого агента**, не пользователю в этом окне.
  Релиз или ветка готовы → `herdr agent prompt tools-root "<репо, ветка, теги,
  что внутри, результат гейта>"`; он спрашивает пользователя и после его «да»
  сам делает `git push --follow-tags` и сообщает. Самому не пушить;
  force-push и `commit --amend` — никогда. Вопрос или решение для пользователя —
  тем же каналом, коротко: вопрос, варианты, рекомендация; пока ждёте — делать
  то, что от ответа не зависит.
- **Сообщать корневому агенту** (в отчёте пользователю, рядом с тегом
  релиза): новая или переименованная переменная окружения / ключ, новая
  локальная база или новый путь к данным, новая или убранная зависимость от
  другого инструмента, обновлённый токен сохраняется локально, ломающий релиз.
- **Потребители**: перед ломающим изменением проверить, кто пользуется
  инструментом (корневой `AGENTS.md` → Service map), и назвать их в отчёте.
- **Серверы Linux без экрана**: сначала переменные окружения, keychain
  необязателен (его отсутствие при заданной переменной — не ошибка); имена
  переменных — уже существующие; без TTY никаких вопросов; без путей только для Mac.
- **Данные** — в общей PostgreSQL (`LLMKIT_DATABASE_URL`) или в локальной SQLite
  в `platformdirs.user_data_dir("llmkit")`, не в репозитории; между ними —
  только через `llm db import-sqlite` (cli-generator `architecture.md` §12).
