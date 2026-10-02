# CLI-конвенции `llm`

Новые группы команд создаются через `output.group(...)` (пустой вызов
печатает help и выходит с 0). Тело команды — внутри `with guard(ctx)`,
результат — через `emit(ctx, payload, render)`; см. `src/llmkit/cli/output.py`.

Коды выхода 0/1/2/3/5/6 — из `conventions.md` скилла cli-builder (файл
самого скилла, не этого репозитория); в коде — `errors.EXIT_CODES`, другой код
роняет `tests/test_describe.py`.

`llm describe --json` — контракт CLI документом OpenCLI для каталога tools и
Windmill (`opencli.py`, из шаблона cli-generator v1.5.1): дерево команд и флагов
из Typer, `exitCodes`, в `metadata` корня — `x-rb-env`, `x-rb-data` (таблицы с
`kind`, представления `llmkit_v1_*` из `db/tables.py` `views`, файлы из
`data_files.py`), `x-rb-external`. Единственный `--json` без конверта `{"ok": ...}`.
Снимок — `tests/snapshots/describe.json`: его дифф — изменение контракта.
