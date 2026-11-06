"""Команда `llm models`: провайдеры routing, источник их ключа и цепочка моделей.

`key_source` — единственное место, где CLI решает, есть ли ключ шлюза: значение
не читается, только наличие переменной окружения.
"""

import os
from typing import Any

import typer
from rich.table import Table

from .. import keys as keys_mod
from . import runtime
from .app import app
from .output import JsonOption, emit, enable_json, guard, out


def key_source(name: str, cfg) -> str:
    """Откуда берётся ключ шлюза: env или его нет — другого источника у llmkit нет."""
    return "env" if os.environ.get(keys_mod.env_var(name, cfg)) else "none"


@app.command("models")
def models(
    ctx: typer.Context,
    routing: str = typer.Option(
        None, "--routing", help="Routing v1: JSON или файл; иначе LLMKIT_ROUTING_FILE, иначе файл по умолчанию."
    ),
    json_output: bool = JsonOption,
) -> None:
    """Показать провайдеров routing, источник их ключей и цепочку моделей.

    Значения ключей не печатаются. Встроенных провайдеров нет: всё — из
    routing (`--routing`, иначе LLMKIT_ROUTING_FILE, иначе routing.json в
    каталоге конфигурации). Коды выхода: 0 — готово, 2 — нет routing, или он не по схеме
    (например, цепочка ссылается на неописанного провайдера).

    Example: llm models --routing routing.json --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        loaded = runtime.load_routing(routing, require_chain=False)
        providers: list[dict[str, Any]] = []
        for name, cfg in sorted(loaded.providers.items()):
            source = key_source(name, cfg)
            providers.append(
                {
                    "provider": name,
                    "protocol": cfg.protocol,
                    "base_url": cfg.base_url,
                    "has_key": source != "none",
                    "key_source": source,
                    "env_var": keys_mod.env_var(name, cfg),
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
