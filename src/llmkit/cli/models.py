"""Команда `llm models`: провайдеры и цепочка из routing."""

from typing import Any

import typer
from rich.table import Table

from . import runtime
from .app import app
from .keys import key_source
from .output import JsonOption, emit, enable_json, guard, out


@app.command("models")
def models(
    ctx: typer.Context,
    routing: str = typer.Option(None, "--routing", help="Routing v1: JSON или файл; иначе LLMKIT_ROUTING_FILE."),
    json_output: bool = JsonOption,
) -> None:
    """Показать провайдеров routing, источник их ключей и цепочку моделей.

    Значения ключей не печатаются. Встроенных провайдеров нет: всё — из
    routing. Коды выхода: 0 — готово, 2 — нет routing, или он не по схеме
    (например, цепочка ссылается на неописанного провайдера).

    Example: llm models --routing routing.json --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        loaded = runtime.load_routing(routing, require_chain=False)
        providers: list[dict[str, Any]] = []
        for name, cfg in sorted(loaded.providers.items()):
            source, env_var = key_source(name, cfg)
            providers.append(
                {
                    "provider": name,
                    "protocol": cfg.protocol,
                    "base_url": cfg.base_url,
                    "has_key": source != "none",
                    "key_source": source,
                    "env_var": env_var,
                }
            )
        chain = list(loaded.chain or [])

        def render() -> None:
            table = Table(title="Провайдеры")
            for column in ("Провайдер", "Протокол", "base_url", "Ключ"):
                table.add_column(column)
            for row in providers:
                table.add_row(row["provider"], row["protocol"], row["base_url"] or "—", row["key_source"])
            out.print(table)
            out.print("Цепочка: " + (" → ".join(chain) or "нет (задаётся вызовом: -m …)"), highlight=False)

        emit(ctx, {"providers": providers, "chain": chain}, render)
