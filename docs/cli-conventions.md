# CLI-конвенции `llm`

Новые группы команд создаются через `output.group(...)` (пустой вызов
печатает help и выходит с 0). Тело команды — внутри `with guard(ctx)`,
результат — через `emit(ctx, payload, render)`; см. `src/llmkit/cli/output.py`.

Коды выхода 0/1/2/3/5 — из `conventions.md` скилла cli-builder (файл
самого скилла, не этого репозитория).
