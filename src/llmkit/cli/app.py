"""Корневое Typer-приложение `llm`: команды верхнего уровня регистрируются на нём `@app.command`."""

import typer

DESCRIPTION = "llmkit: вызовы LLM с цепочками моделей, кэшем и учётом расходов"

app = typer.Typer(
    name="llm",
    help=(
        f"{DESCRIPTION}.\n\n"
        "У всех команд есть `--json` (конверт в stdout), диагностика идёт в stderr.\n"
        "Коды выхода: 0 — успех, 1 — непредвиденная ошибка, 2 — неверные аргументы,\n"
        "3 — нет ключа или входа в подписку, 5 — все модели упали или база недоступна,\n"
        "6 — базу расходов смигрировал более новый релиз (`llm db`).\n\n"
        "Основные параметры `llm ask` и `llm json`:\n\n"
        "  -m, --model ПРОВАЙДЕР/МОДЕЛЬ   одна модель вместо уровня: ccode/gpt-5.6-sol\n\n"
        "  -l, --level УРОВЕНЬ            цепочка моделей из конфига: cheap, judge…\n\n"
        "  -s, --system ТЕКСТ             системное сообщение\n\n"
        "  --schema ФАЙЛ                  JSON Schema ответа (только llm json)\n\n"
        "  --temperature, --max-tokens, --timeout   перекрыть значения из конфига\n\n"
        "  --tag k=v                      метка для учёта расходов, можно несколько\n\n"
        "  --no-cache, --no-retry         без кэша; без повторов на сбойной модели\n\n"
        "Список провайдеров, уровней и моделей: `llm models`. Все параметры\n"
        "команды: `llm <команда> --help`, например `llm ask --help`.\n\n"
        "Примеры:\n\n"
        '  llm ask "Столица Франции?" --level cheap\n\n'
        '  llm ask "Привет" -m ccode/gpt-5.6-sol\n\n'
        '  llm json "Разбери запрос" --schema schema.json\n\n'
        "  llm models · llm cost --since 7d · llm auth status · llm db status"
    ),
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
)
