"""Команды `llm ask` и `llm json`: один вызов модели."""

import json
from pathlib import Path

import typer

from ..core import Task
from . import runtime
from .output import JsonOption, bad_arguments, emit, enable_json, guard, out


def _answer_payload(answer) -> dict:
    return {
        "data": answer.data,
        "source": answer.source,
        "model": answer.model,
        "provider": answer.provider,
        "prompt_tokens": answer.prompt_tokens,
        "completion_tokens": answer.completion_tokens,
        "cost_usd": answer.cost_usd,
        "cost_known": answer.cost_known,
        "latency_ms": answer.latency_ms,
        "warnings": answer.warnings,
    }


def _run(text, system, level, model, tags, no_cache, temperature, max_tokens, schema):
    kit = runtime.build_kit()
    task = Task(
        user=runtime.read_text(text),
        system=system,
        schema=schema,
        level=level,
        chain=[model] if model else None,
        tags=runtime.parse_tags(tags),
        temperature=temperature,
        max_tokens=max_tokens,
        cache=False if no_cache else None,
    )
    answer = kit.ask_sync(task)
    for warning in answer.warnings:
        typer.echo(warning, err=True)
    return answer


def ask(
    ctx: typer.Context,
    text: str = typer.Argument(None, help="Текст запроса; без него читается stdin."),
    system: str = typer.Option(None, "--system", "-s", help="Системное сообщение."),
    level: str = typer.Option(None, "--level", "-l", help="Уровень из конфига: cheap, judge, strong…"),
    model: str = typer.Option(None, "--model", "-m", help="Конкретная модель 'провайдер/модель' вместо уровня."),
    tag: list[str] = typer.Option(None, "--tag", help="Метка k=v для учёта расходов; можно несколько."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Не читать и не писать кэш ответов."),
    temperature: float = typer.Option(None, "--temperature", help="Температура; по умолчанию из конфига."),
    max_tokens: int = typer.Option(None, "--max-tokens", help="Лимит токенов ответа."),
    json_output: bool = JsonOption,
) -> None:
    """Задать вопрос модели и напечатать текстовый ответ.

    Цепочка моделей берётся из уровня конфига; упавшая модель уступает
    следующей. Коды выхода: 0 — ответ получен, 1 — все модели упали или нет
    ключа, 2 — неверные аргументы.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        answer = _run(text, system, level, model, tag, no_cache, temperature, max_tokens, None)
        emit(ctx, _answer_payload(answer), lambda: out.print(answer.data, highlight=False, markup=False))


def json_command(
    ctx: typer.Context,
    text: str = typer.Argument(None, help="Текст запроса; без него читается stdin."),
    schema: Path = typer.Option(..., "--schema", help="Файл с JSON Schema ответа."),
    system: str = typer.Option(None, "--system", "-s", help="Системное сообщение."),
    level: str = typer.Option(None, "--level", "-l", help="Уровень из конфига: cheap, judge, strong…"),
    model: str = typer.Option(None, "--model", "-m", help="Конкретная модель 'провайдер/модель' вместо уровня."),
    tag: list[str] = typer.Option(None, "--tag", help="Метка k=v для учёта расходов; можно несколько."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Не читать и не писать кэш ответов."),
    temperature: float = typer.Option(None, "--temperature", help="Температура; по умолчанию из конфига."),
    max_tokens: int = typer.Option(None, "--max-tokens", help="Лимит токенов ответа."),
    json_output: bool = JsonOption,
) -> None:
    """Получить ответ модели как JSON по схеме.

    В обычном режиме в stdout попадает только сам объект ответа, в режиме
    `--json` — конверт с полем `data` и метаданными вызова. Валидацию по
    схеме выполняет потребитель. Коды выхода: 0 — ответ получен, 1 — все
    модели упали или ответ не разобрался, 2 — неверные аргументы.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        try:
            loaded = json.loads(schema.read_text(encoding="utf-8"))
        except OSError as exc:
            raise bad_arguments(f"схема не читается: {exc}") from exc
        except ValueError as exc:
            raise bad_arguments(f"схема не разбирается как JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise bad_arguments("схема должна быть JSON-объектом")
        answer = _run(text, system, level, model, tag, no_cache, temperature, max_tokens, loaded)
        emit(
            ctx,
            _answer_payload(answer),
            lambda: print(json.dumps(answer.data, ensure_ascii=False, indent=2)),
        )
