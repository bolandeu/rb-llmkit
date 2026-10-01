"""Команды `llm db`: база журнала расходов (общая PostgreSQL или локальная SQLite)."""

from pathlib import Path

import typer

from .output import JsonOption, emit, enable_json, group, guard, out

app = group("db", "База журнала расходов: общая PostgreSQL (LLMKIT_DATABASE_URL) или локальная SQLite.")

DryRunOption = typer.Option(False, "--dry-run", help="Показать, что будет сделано, ничего не меняя.")


def _state(engine) -> dict:
    from .. import db

    state = db.schema_state(engine)
    return {
        "database": db.describe(engine),
        "current": state.current,
        "head": state.head,
        "up_to_date": state.up_to_date,
    }


def _print(payload: dict) -> None:
    for name, value in payload.items():
        out.print(f"{name}: {'—' if value is None else value}", highlight=False)


@app.command("status")
def status(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать, какая база используется и её ревизию схемы против ревизии этой версии.

    Коды выхода: 0 — готово, 5 — база из LLMKIT_DATABASE_URL недоступна.

    Example: llm db status --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        from .. import db

        engine = db.open_db(check=False)
        try:
            payload = _state(engine)
        finally:
            engine.dispose()
        emit(ctx, payload, lambda: _print(payload))


@app.command("upgrade")
def upgrade(ctx: typer.Context, dry_run: bool = DryRunOption, json_output: bool = JsonOption) -> None:
    """Применить недостающие миграции схемы к базе.

    Общая PostgreSQL неявно не мигрируется: запускайте выпущенной версией после
    обновления, которое несёт миграции. Одновременные запуски ждут друг друга.
    Локальная SQLite и так мигрируется при каждом открытии. Коды выхода: 0 —
    готово, 5 — база недоступна, 6 — базу смигрировал более новый релиз.

    Example: llm db upgrade --dry-run
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        from .. import db

        engine = db.open_db(check=False)
        try:
            before = _state(engine)
            if dry_run:
                payload = {**before, "dry_run": True}
                message = (
                    "Dry run: схема актуальна."
                    if before["up_to_date"]
                    else f"Dry run: будет миграция {before['current']} → {before['head']}."
                )
                emit(ctx, payload, lambda: out.print(message, highlight=False))
                return
            db.upgrade(engine)
            after = _state(engine)
        finally:
            engine.dispose()
        payload = {**after, "previous": before["current"]}
        message = (
            f"Схема актуальна: {after['head']}."
            if before["current"] == after["head"]
            else f"Смигрировано {before['current']} → {after['head']}."
        )
        emit(ctx, payload, lambda: out.print(message, highlight=False))


@app.command("import-sqlite")
def import_sqlite(
    ctx: typer.Context,
    path: Path = typer.Argument(None, help="Файл SQLite для импорта (по умолчанию — локальный журнал, usage.path)."),
    dry_run: bool = DryRunOption,
    json_output: bool = JsonOption,
) -> None:
    """Скопировать локальную SQLite в настроенную базу, один раз.

    Для переезда в общую PostgreSQL: задайте LLMKIT_DATABASE_URL и запустите.
    Каждая целевая таблица должна быть пустой; все строки — одной транзакцией.
    Коды выхода: 0 — готово, 1 — база не смигрирована, 2 — нет файла или
    таблица не пуста, 5 — база недоступна.

    Example: llm db import-sqlite --dry-run
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        from .. import db

        source = path or db.sqlite_path()
        engine = db.open_db()
        try:
            counts = db.import_sqlite(source, engine, dry_run=dry_run)
        finally:
            engine.dispose()
        payload = {"source": str(source), "dry_run": dry_run, "rows": counts}
        verb = "Будет импортировано" if dry_run else "Импортировано"

        def render() -> None:
            out.print(f"{verb} из {source}:", highlight=False)
            _print(counts)

        emit(ctx, payload, render)
