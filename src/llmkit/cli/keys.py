"""Команды `llm keys`: ключи провайдеров в связке ключей ОС."""

import os
import sys

import typer

from .. import config as config_mod
from .. import keys as keys_mod
from ..providers import SUBSCRIPTION_KINDS
from .output import JsonOption, bad_arguments, emit, enable_json, group, guard, out

app = group("keys", "Ключи провайдеров: связка ключей ОС и переменные окружения.")


def _known_provider(name: str):
    config = config_mod.load()
    if name not in config.providers:
        known = ", ".join(sorted(config.providers))
        raise bad_arguments(f"провайдер {name!r} не описан в конфиге; известные: {known}")
    return config.providers[name]


def key_source(name: str, cfg) -> tuple[str, str]:
    """Откуда берётся ключ: env, keychain, config или его нет."""
    env_var = keys_mod.env_var(name, cfg)
    if cfg.kind in SUBSCRIPTION_KINDS:
        return "subscription", ""
    if cfg.api_key:
        return "config", env_var
    if os.environ.get(env_var):
        return "env", env_var
    if keys_mod.from_keychain(name):
        return "keychain", env_var
    return "none", env_var


@app.command("set")
def set_key(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Имя провайдера из конфига, например openrouter."),
    from_stdin: bool = typer.Option(False, "--stdin", help="Прочитать ключ из stdin вместо скрытого ввода."),
    json_output: bool = JsonOption,
) -> None:
    """Положить ключ провайдера в связку ключей ОС.

    Ключ нигде не печатается. Коды выхода: 0 — сохранён, 1 — связка ключей
    недоступна, 2 — неизвестный провайдер или пустой ключ.
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
def status(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать, откуда берётся ключ каждого провайдера.

    Значения ключей не печатаются — только источник: config, env, keychain
    или none. Код выхода 0, даже если ключей нет.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        rows = []
        for name, cfg in sorted(config.providers.items()):
            source, env_var = key_source(name, cfg)
            rows.append(
                {
                    "provider": name,
                    "kind": cfg.kind,
                    "source": source,
                    "env_var": env_var,
                    "requires_key": cfg.requires_key,
                }
            )

        def render() -> None:
            from rich.table import Table

            table = Table(title="Ключи провайдеров")
            for column in ("Провайдер", "Вид", "Источник", "Переменная окружения"):
                table.add_column(column)
            for row in rows:
                mark = row["source"] if row["source"] != "none" else ("нет" if row["requires_key"] else "не нужен")
                if row["source"] == "subscription":
                    mark = "подписка: `llm auth status`"
                table.add_row(row["provider"], row["kind"], mark, row["env_var"])
            out.print(table)

        emit(ctx, {"providers": rows}, render)


@app.command("rm")
def remove(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Имя провайдера из конфига."),
    json_output: bool = JsonOption,
) -> None:
    """Удалить ключ провайдера из связки ключей.

    Удаление отсутствующего ключа не ошибка. Коды выхода: 0 — готово,
    2 — неизвестный провайдер.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _known_provider(provider)
        keys_mod.delete(provider)
        emit(ctx, {"provider": provider, "removed": True}, lambda: out.print(f"Ключ провайдера {provider} удалён."))
