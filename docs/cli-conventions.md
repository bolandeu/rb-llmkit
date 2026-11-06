# CLI-конвенции `llm`

Новые группы команд создаются через `output.group(...)` (пустой вызов
печатает help и выходит с 0). Тело команды — внутри `with guard(ctx)`,
результат — через `emit(ctx, payload, render)`; см. `src/llmkit/cli/output.py`.

Коды выхода 0/1/2/3/5 — из `conventions.md` скилла cli-builder (файл самого
скилла, не этого репозитория; 4 и 6 у llmkit не бывает); в коде —
`errors.EXIT_CODES`, другой код роняет `tests/test_describe.py`.

`llm describe --json` — контракт CLI документом OpenCLI для каталога tools и
Windmill (`opencli.py`, из шаблона cli-generator v1.5.6): дерево команд и флагов
из Typer, `exitCodes`, в `metadata` корня — `x-rb-env`, `x-rb-data` (файлы из
`data_files.py`; таблиц и представлений у llmkit нет), `x-rb-external`.
Единственный `--json` без конверта `{"ok": ...}`.
Снимок — `tests/snapshots/describe.json`: его дифф — изменение контракта.
