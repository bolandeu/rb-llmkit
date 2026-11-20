"""Корневое Typer-приложение `llm`: команды верхнего уровня регистрируются на нём `@app.command`."""

import typer

from .output import RootGroup

DESCRIPTION = "llmkit: вызовы LLM только через шлюз 9router"

app = typer.Typer(
    cls=RootGroup,
    name="llm",
    help=(
        f"{DESCRIPTION}.\n\n"
        "У всех команд есть `--json` (конверт в stdout), диагностика идёт в stderr.\n"
        "Коды выхода: 0 — успех, 1 — непредвиденная ошибка, 2 — неверные аргументы,\n"
        "3 — нет переменной с ключом шлюза, 5 — шлюз недоступен, ответил ошибкой или\n"
        "его журнал расходов не читается.\n\n"
        "Провайдеры и цепочка — routing v1 (данные, встроенных нет):\n\n"
        "  --routing JSON|ФАЙЛ             routing аргументом или файлом; иначе LLMKIT_ROUTING_FILE,\n"
        "                                 иначе routing.json в каталоге конфигурации\n\n"
        "  -m ПРОВАЙДЕР/МОДЕЛЬ             цепочка из CLI, можно несколько: -m a/x -m b/y\n\n"
        "  -s, --system ТЕКСТ             системное сообщение\n\n"
        "  --schema ФАЙЛ                  JSON Schema ответа (только llm json)\n\n"
        "  --template ФАЙЛ --vars JSON     шаблон промпта mustache вместо текста\n\n"
        "  --temperature, --max-tokens, --timeout   перекрыть значения по умолчанию\n\n"
        "  --tag k=v                      метка k=v в строке лога вызова, можно несколько\n\n"
        "  --no-retry                     без повтора невалидного ответа\n\n"
        "Ключ шлюза — переменная из routing (`key_env`), только из окружения.\n"
        "Старый config.toml не читается: `llm routing import config.toml`.\n\n"
        "Провайдеры routing и источник ключа: `llm models`. Все параметры\n"
        "команды: `llm <команда> --help`, например `llm ask --help`.\n\n"
        "Примеры:\n\n"
        '  llm ask "Столица Франции?" --routing routing.json\n\n'
        '  llm ask "Привет" -m "Deep Sec"\n\n'
        '  llm json "Разбери запрос" --schema schema.json\n\n'
        "  llm routing validate routing.json · llm models · llm cost --since 7d · llm auth status"
    ),
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
)
