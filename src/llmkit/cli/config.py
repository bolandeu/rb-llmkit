"""Команды `llm config`: путь, итоговый конфиг, шаблон."""

import os
from pathlib import Path

import typer

from .. import config as config_mod
from .output import JsonOption, bad_arguments, emit, enable_json, group, guard, out

app = group("config", "Конфиг llmkit: где лежит, что получилось, как начать.")

# Шаблон из раздела 3 спецификации: все поля с дефолтными значениями.
TEMPLATE = """# Конфиг llmkit. Слои: дефолты в коде → этот файл →
# .llmkit/config.toml проекта → LLMKIT_* → аргументы LlmKit(...).

[providers.openrouter]
kind = "openrouter"                 # openrouter | openai | anthropic | gemini | ollama | openai_compatible
# ключ: переменная OPENROUTER_API_KEY или связка ключей (llm keys set openrouter)

[providers.ollama]
kind = "ollama"
base_url = "https://ollama.com"     # локальный: http://localhost:11434
[providers.ollama.prices]           # $ за 1M токенов; главнее цен LiteLLM
"gpt-oss:120b" = { input = 0.15, output = 0.60 }

[levels]
# Уровень = цепочка "провайдер/модель" по порядку: упала первая — отвечает следующая.
# Ниже пример; модели выбирайте сами. "провайдер" — ключ из [providers] выше,
# всё после первого "/" — имя модели у этого провайдера.
cheap  = ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"]
judge  = ["openrouter/anthropic/claude-sonnet-4", "openrouter/openai/gpt-4o"]
strong = ["openrouter/anthropic/claude-opus-4"]

[defaults]
level = "cheap"
temperature = 0.0
timeout = 120                       # секунд на один HTTP-вызов
max_tokens = 4096
concurrency = 6                     # параллельных вызовов в ask_many

[cache]
enabled = true
ttl_days = 30

[budget]                            # только предупреждения, ничего не прерывает
daily_usd = 20.0
# Лимит на значение метки — раскомментируйте нужные:
# [budget.tags]
# "tool=intentree" = 2.0

[retry]                             # повторы по типам ошибок
timeout = 1
rate_limit = 2
server = 2
invalid_output = 2
"""


def _target() -> Path:
    """Куда пишет `init`: LLMKIT_CONFIG, если задан, иначе пользовательский конфиг."""
    explicit = os.environ.get("LLMKIT_CONFIG")
    return Path(explicit) if explicit else config_mod.user_config_path()


def _hide_keys(data: dict) -> dict:
    """Убрать значения ключей из дампа конфига."""
    for provider in data.get("providers", {}).values():
        if provider.get("api_key"):
            provider["api_key"] = "***"
    return data


def _drop_none(value):
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


@app.command("path")
def path(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать пути конфига, кэша и журнала вызовов.

    Код выхода всегда 0.

    Example: llm config path
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        project = config_mod.project_config_path()
        payload = {
            "user": str(config_mod.user_config_path()),
            "project": str(project) if project else None,
            "explicit": os.environ.get("LLMKIT_CONFIG"),
            "cache": str(config.cache_path()),
            "usage": str(config.usage_path()),
        }

        def render() -> None:
            for name, value in payload.items():
                out.print(f"{name}: {value or '—'}")

        emit(ctx, payload, render)


@app.command("show")
def show(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать итоговый конфиг после слияния всех слоёв.

    Значения ключей не печатаются. Коды выхода: 0 — готово, 2 — конфиг не
    разбирается.

    Example: llm config show --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = _hide_keys(config_mod.load().model_dump(mode="json"))

        def render() -> None:
            import tomli_w

            out.print(tomli_w.dumps(_drop_none(data)), highlight=False, markup=False)

        emit(ctx, {"config": data}, render)


@app.command("init")
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Перезаписать существующий файл."),
    json_output: bool = JsonOption,
) -> None:
    """Записать шаблон конфига.

    Существующий файл без `--force` не трогается. Коды выхода: 0 — файл
    создан, 2 — файл уже есть.

    Example: llm config init
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        target = _target()
        if target.exists() and not force:
            raise bad_arguments(f"конфиг уже есть: {target}", "перезаписать — `llm config init --force`")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(TEMPLATE, encoding="utf-8")
        emit(ctx, {"path": str(target), "created": True}, lambda: out.print(f"Конфиг записан: {target}"))
