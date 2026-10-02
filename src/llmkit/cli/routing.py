"""Команды `llm routing`: перенос старого config.toml и проверка routing v1."""

import json
import tomllib
from pathlib import Path

import typer

from .. import legacy
from .. import routing as routing_mod
from .output import JsonOption, bad_arguments, emit, enable_json, err, group, guard, out

app = group("routing", "Routing v1: провайдеры, цепочка и цены данными — проверка и перенос старого config.toml.")


@app.command("import")
def import_config(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="config.toml llmkit < 0.8 (только читается)."),
    json_output: bool = JsonOption,
) -> None:
    """Перенести старый config.toml в routing v1.

    Провайдеры (с адресами бывших встроенных) и цены — в `routing`, без
    цепочки: её задаёт вызов (`-m …`) или вы. Уровни — отдельно в `levels`,
    подсказкой для своих цепочек. Ключи не переносятся: `key_env` —
    LLM_<ПРОВАЙДЕР>_API_KEY. Секции defaults, cache, budget, retry
    перечислены в `dropped`. В stdout — JSON {routing, levels, warnings,
    dropped}. Коды выхода: 0 — готово, 2 — файл не читается или не TOML.

    Example: llm routing import config.toml > routing.json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        try:
            old = legacy.read(path)
        except OSError as exc:
            raise bad_arguments(f"не читается {path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise bad_arguments(f"битый TOML в {path}: {exc}") from exc
        result = legacy.convert(old)

        def render() -> None:
            for warning in result["warnings"]:
                err.print(warning, highlight=False, markup=False)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        emit(ctx, result, render)


@app.command("validate")
def validate(
    ctx: typer.Context,
    routing: str = typer.Argument(..., help="Routing v1: путь к JSON-файлу или JSON-строка."),
    providers_only: bool = typer.Option(
        False, "--providers-only", help="Без цепочки: файл провайдеров под `-m …` (LLMKIT_ROUTING_FILE)."
    ),
    json_output: bool = JsonOption,
) -> None:
    """Проверить routing v1 перед сохранением (Windmill, Directus).

    Та же проверка, что перед вызовом модели: схема плюс ссылки цепочки и
    цен на описанных провайдеров. Ключи не проверяются (`llm auth status`).
    Коды выхода: 0 — routing годен, 2 — ROUTING_INVALID с `error.path`
    (JSON Pointer поля).

    Example: llm routing validate '{"providers": {"openrouter": {"protocol": "openrouter"}}, "chain": ["openrouter/openai/gpt-4o-mini"]}'
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        parsed = routing_mod.parse(routing_mod.load(routing), require_chain=not providers_only)
        payload = {"providers": sorted(parsed.providers), "chain": parsed.chain or []}
        emit(ctx, payload, lambda: out.print("routing годен", highlight=False))
