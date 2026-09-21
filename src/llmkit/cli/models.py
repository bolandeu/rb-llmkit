"""Команда `llm models`: провайдеры, уровни и цепочки из конфига."""

import typer
from rich.table import Table

from .. import config as config_mod
from .keys import key_source
from .output import JsonOption, emit, enable_json, guard, out


def models(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать провайдеров, уровни и их цепочки моделей.

    У каждого провайдера видно, откуда берётся ключ (значение не
    печатается). Код выхода 0; 2 — если конфиг не разбирается.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        providers = []
        for name, cfg in sorted(config.providers.items()):
            source, env_var = key_source(name, cfg)
            providers.append(
                {
                    "provider": name,
                    "kind": cfg.kind,
                    "base_url": cfg.base_url,
                    "has_key": source != "none",
                    "key_source": source,
                    "env_var": env_var,
                }
            )
        levels = {name: list(chain) for name, chain in sorted(config.levels.items())}

        def render() -> None:
            table = Table(title="Провайдеры")
            for column in ("Провайдер", "Вид", "base_url", "Ключ"):
                table.add_column(column)
            for row in providers:
                table.add_row(row["provider"], row["kind"], row["base_url"] or "—", row["key_source"])
            out.print(table)
            chains = Table(title="Уровни")
            chains.add_column("Уровень")
            chains.add_column("Цепочка моделей")
            for name, chain in levels.items():
                mark = " (по умолчанию)" if name == config.defaults.level else ""
                chains.add_row(name + mark, " → ".join(chain))
            out.print(chains)

        emit(ctx, {"providers": providers, "levels": levels, "default_level": config.defaults.level}, render)
