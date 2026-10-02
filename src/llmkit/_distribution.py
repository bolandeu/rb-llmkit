# Имя дистрибутива: [project] name в pyproject.toml (стандарт §10: `rb-<slug>`),
# отличается от имени импорт-пакета. По нему importlib.metadata находит версию;
# editable-установку (`uv sync`) по пакету в дистрибутив не отобразить, поэтому
# имя записано здесь. tests/test_cli.py падает, если оно разойдётся с pyproject.toml.
DIST_NAME = "rb-llmkit"
# Прежнее имя дистрибутива на время переименования (стандарт §10): установка под
# ним (ещё не переустановленная) по-прежнему находит свою версию. Убрать, когда
# на всех машинах стоит новое имя.
DIST_NAME_LEGACY: str | None = "llmkit"
# Имя инструмента для общей базы (cli-generator architecture.md §12): префикс таблиц
# `llmkit_`, переменная `LLMKIT_DATABASE_URL`. Записано, а не выводится из имени CLI (`llm`).
TOOL = "llmkit"
# Релиз cli-generator, с которым сверен перенесённый вручную код (слой БД,
# describe; AGENTS.md) — для `llm describe --json`. copier у llmkit нет.
TEMPLATE_VERSION: str | None = "v1.5.0"
