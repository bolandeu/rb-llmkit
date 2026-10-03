"""Команды `llm keys`: ключи провайдеров в связке ключей ОС."""

import os
import re
import sys
from typing import Any

import typer

from .. import keys as keys_mod
from . import runtime
from .output import JsonOption, bad_arguments, emit, enable_json, group, guard, out

app = group("keys", "Ключи провайдеров: связка ключей ОС и переменные окружения.")


def _known_provider(name: str) -> None:
    """Связка ключей хранит ключ по имени провайдера routing (`llmkit:<провайдер>`)."""
    if not re.match(r"^[A-Za-z0-9_.-]+$", name):
        raise bad_arguments(f"имя провайдера {name!r}: латиница, цифры, _ . - (как в routing.providers)")


def key_source(name: str, cfg) -> tuple[str, str]:
    """Откуда берётся ключ: env, legacy_env (старое имя), keychain или его нет."""
    env_var = keys_mod.env_var(name, cfg)
    if cfg.subscription:
        return "subscription", ""
    if os.environ.get(env_var):
        return "env", env_var
    legacy = keys_mod.legacy_env(name, cfg)
    if legacy != env_var and os.environ.get(legacy):
        return "legacy_env", legacy
    if keys_mod.from_keychain(name):
        return "keychain", env_var
    return "none", env_var


@app.command("set")
def set_key(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Имя провайдера из routing, например openrouter."),
    from_stdin: bool = typer.Option(False, "--stdin", help="Прочитать ключ из stdin вместо скрытого ввода."),
    json_output: bool = JsonOption,
) -> None:
    """Положить ключ провайдера в связку ключей ОС.

    Ключ нигде не печатается; он читается, когда в env нет
    LLM_<ПРОВАЙДЕР>_API_KEY. Коды выхода: 0 — сохранён, 1 — связка ключей
    недоступна, 2 — неверное имя провайдера или пустой ключ.

    Example: echo "$KEY" | llm keys set openrouter --stdin
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _known_provider(provider)
        secret = sys.stdin.read().strip() if from_stdin else typer.prompt("Ключ", hide_input=True).strip()
        if not secret:
            raise bad_arguments("ключ пустой")
        keys_mod.store(provider, secret)
        emit(
            ctx,
            {"provider": provider, "stored": True},
            lambda: out.print(f"Ключ провайдера {provider} сохранён в связке ключей."),
        )


@app.command("status")
def status(
    ctx: typer.Context,
    routing: str = typer.Option(
        None, "--routing", help="Routing v1: JSON или файл; иначе LLMKIT_ROUTING_FILE, иначе файл по умолчанию."
    ),
    json_output: bool = JsonOption,
) -> None:
    """Показать, откуда берётся ключ каждого провайдера routing.

    Routing — `--routing`, иначе LLMKIT_ROUTING_FILE, иначе routing.json в
    каталоге конфигурации (`llm config path`).

    Значения ключей не печатаются — только источник: env, legacy_env
    (старое имя переменной), keychain, subscription или none. Коды выхода:
    0 — готово (даже если ключей нет), 2 — нет routing или он не по схеме.

    Example: llm keys status --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        loaded = runtime.load_routing(routing, require_chain=False)
        rows: list[dict[str, Any]] = []
        for name, cfg in sorted(loaded.providers.items()):
            source, env_var = key_source(name, cfg)
            rows.append({"provider": name, "protocol": cfg.protocol, "source": source, "env_var": env_var})

        def render() -> None:
            from rich.table import Table

            table = Table(title="Ключи провайдеров")
            for column in ("Провайдер", "Протокол", "Источник", "Переменная окружения"):
                table.add_column(column)
            for row in rows:
                mark = row["source"] if row["source"] != "none" else "нет"
                if row["source"] == "subscription":
                    mark = "подписка: `llm auth status`"
                table.add_row(row["provider"], row["protocol"], mark, row["env_var"])
            out.print(table)

        emit(ctx, {"providers": rows}, render)


@app.command("rm")
def remove(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Имя провайдера из routing."),
    json_output: bool = JsonOption,
) -> None:
    """Удалить ключ провайдера из связки ключей.

    Удаление отсутствующего ключа не ошибка. Коды выхода: 0 — готово,
    2 — неверное имя провайдера.

    Example: llm keys rm openrouter
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _known_provider(provider)
        keys_mod.delete(provider)
        emit(ctx, {"provider": provider, "removed": True}, lambda: out.print(f"Ключ провайдера {provider} удалён."))
