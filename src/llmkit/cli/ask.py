"""Команды `llm ask` и `llm json`: один вызов модели через шлюз 9router."""

import json
import uuid
from pathlib import Path

import typer

from ..core import Task
from . import runtime
from .app import app
from .output import JsonOption, bad_arguments, emit, enable_json, guard, out
from .render import LenientOption, TemplateOption, VarsOption, prompt_text

RoutingOption = typer.Option(
    None,
    "--routing",
    help="Routing v1: JSON-строка или путь к JSON-файлу; без него — LLMKIT_ROUTING_FILE, затем routing.json в каталоге конфигурации (llm config path). Не stdin.",
)
ModelsOption = typer.Option(
    None,
    "--model",
    "-m",
    help="Модель или комбо шлюза строкой как в его настройке; повторяется — цепочка (вместо routing.chain). Фолбэк исполняет шлюз.",
)
# Уровней больше нет: флаг оставлен скрытым, чтобы объяснить, чем его заменить.
LevelOption = typer.Option(None, "--level", "-l", hidden=True, help="Удалён: передайте цепочку.")


def _reject_level(level: str | None) -> None:
    if level is not None:
        raise bad_arguments(
            "--level удалён: уровней в llmkit больше нет",
            "передайте цепочку: -m модель (можно несколько) или routing.chain",
        )


COST_CURRENCY = "USD"


def _answer_payload(answer, data_key: str) -> dict:
    """Ответ `--json` (контракт для Windmill): ключи и переменные шаблона сюда не попадают."""
    return {
        data_key: answer.data,
        "task_id": answer.task_id,
        "model": answer.model,
        "served_model": answer.served_model,
        "provider": answer.provider,
        "chain_position": answer.chain_position,
        "attempts": [{"model": a.model, "error_code": a.error_type} for a in answer.attempts if a.error_type],
        "tokens_in": answer.prompt_tokens,
        "tokens_out": answer.completion_tokens,
        "cost": answer.cost_usd,
        "cost_currency": COST_CURRENCY,
        "cost_source": answer.cost_source,
        "billable_requests": answer.billable_requests,
        "cost_total": answer.cost_total,
        "cost_usd": answer.cost_usd,  # устарело (= cost): Windmill читает его до перехода на cost
        "cache_hit": answer.cache_hit,
        "latency_ms": answer.latency_ms,
        "warnings": answer.warnings,
    }


def _task_id() -> str:
    """Id вызова CLI: попадает в учёт (llmkit_calls.task_id) и в конверт `--json`."""
    return uuid.uuid4().hex


def _echo_warnings(answer) -> None:
    for warning in answer.warnings:
        typer.echo(warning, err=True)


def _run(prompt, routing, system, tags, no_cache, temperature, max_tokens, timeout, no_retry, schema):
    text, template_tags = prompt
    kit = runtime.build_kit(routing=routing)
    task = Task(
        user=runtime.read_text(text),
        system=system,
        schema=schema,
        tags={**runtime.parse_tags(tags), **template_tags},
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        cache=False if no_cache else None,
        retry=not no_retry,
        id=_task_id(),
    )
    answer = kit.ask_sync(task)
    _echo_warnings(answer)
    return answer


@app.command("ask")
def ask(
    ctx: typer.Context,
    text: str = typer.Argument(None, help="Текст запроса; без него читается stdin."),
    system: str = typer.Option(None, "--system", "-s", help="Системное сообщение."),
    routing: str = RoutingOption,
    model: list[str] = ModelsOption,
    level: str = LevelOption,
    tag: list[str] = typer.Option(None, "--tag", help="Метка k=v для учёта расходов; можно несколько."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Не читать и не писать кэш ответов."),
    temperature: float = typer.Option(None, "--temperature", help="Температура; по умолчанию 0."),
    max_tokens: int = typer.Option(None, "--max-tokens", help="Лимит токенов ответа."),
    timeout: float = typer.Option(None, "--timeout", help="Таймаут вызова в секундах."),
    no_retry: bool = typer.Option(False, "--no-retry", help="Не повторять вызов, если ответ не прошёл проверку схемы."),
    template: str = TemplateOption,
    variables: str = VarsOption,
    lenient: bool = LenientOption,
    json_output: bool = JsonOption,
) -> None:
    """Задать вопрос шлюзу и напечатать текстовый ответ.

    Шлюз — из routing v1 (`--routing` JSON или файл, иначе LLMKIT_ROUTING_FILE,
    иначе routing.json в каталоге конфигурации — путь в `llm config path`);
    встроенных нет. Один вызов — один запрос к шлюзу: цепочку и фолбэк
    исполняет он, llmkit просит первую модель `-m` или `routing.chain`.
    Модель — строка как в настройке шлюза (комбо тоже). Вместо текста —
    шаблон: `--template` с `--vars` (в учёт расходов — имя и хэш шаблона,
    без значений). В `--json`: text, task_id (= task_id в учёте), model
    (запрошенная строка), served_model (что назвал шлюз), provider, attempts,
    tokens_in/out, cache_hit и стоимость: cost (usage.cost шлюза),
    cost_currency "USD", cost_source — provider или null (цены в ответе нет;
    provider и cost 0 у подписочного провайдера — норма, не ошибка),
    billable_requests, cost_total. cost_usd = cost, устарело.
    Коды выхода: 0 — ответ получен, 2 — нет routing, routing не по схеме или
    неверные аргументы, 3 — нет ключа шлюза, 5 — шлюз недоступен, ответил
    ошибкой или ответ невалиден.

    Example: llm ask "Столица Франции?" --routing routing.json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _reject_level(level)
        resolved = runtime.call_routing(routing, model)
        prompt = prompt_text(text, template, variables, lenient)
        answer = _run(prompt, resolved, system, tag, no_cache, temperature, max_tokens, timeout, no_retry, None)
        emit(ctx, _answer_payload(answer, "text"), lambda: out.print(answer.data, highlight=False, markup=False))


@app.command("json")
def json_command(
    ctx: typer.Context,
    text: str = typer.Argument(None, help="Текст запроса; без него читается stdin."),
    schema: Path = typer.Option(..., "--schema", help="Файл с JSON Schema ответа."),
    system: str = typer.Option(None, "--system", "-s", help="Системное сообщение."),
    routing: str = RoutingOption,
    model: list[str] = ModelsOption,
    level: str = LevelOption,
    tag: list[str] = typer.Option(None, "--tag", help="Метка k=v для учёта расходов; можно несколько."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Не читать и не писать кэш ответов."),
    temperature: float = typer.Option(None, "--temperature", help="Температура; по умолчанию 0."),
    max_tokens: int = typer.Option(None, "--max-tokens", help="Лимит токенов ответа."),
    timeout: float = typer.Option(None, "--timeout", help="Таймаут вызова в секундах."),
    no_retry: bool = typer.Option(
        False, "--no-retry", help="Не повторять вызов, если ответ не разобрался как JSON по схеме."
    ),
    template: str = TemplateOption,
    variables: str = VarsOption,
    lenient: bool = LenientOption,
    json_output: bool = JsonOption,
) -> None:
    """Получить ответ модели как JSON по схеме.

    Схема уходит в шлюз как `response_format` json_schema; невалидный или
    неразобранный ответ повторяется с текстом ошибки проверки (retry.invalid_output).
    В обычном режиме в stdout попадает только сам объект ответа, в режиме
    `--json` — конверт с полем `data` и метаданными вызова, как у `llm ask`.
    Routing, `-m` и `--template/--vars` — как у `llm ask`. Валидацию значения
    по схеме выполняет потребитель. Невалидный ответ шлюз списал: он в
    billable_requests и cost_total. Коды выхода: 0 — ответ получен,
    2 — неверные аргументы или routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответ не разобрался (в error — billable_requests, cost_total).

    Example: llm json "Разбери запрос" --schema schema.json --routing routing.json --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _reject_level(level)
        try:
            loaded = json.loads(schema.read_text(encoding="utf-8"))
        except OSError as exc:
            raise bad_arguments(f"схема не читается: {exc}") from exc
        except ValueError as exc:
            raise bad_arguments(f"схема не разбирается как JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise bad_arguments("схема должна быть JSON-объектом")
        resolved = runtime.call_routing(routing, model)
        prompt = prompt_text(text, template, variables, lenient)
        answer = _run(prompt, resolved, system, tag, no_cache, temperature, max_tokens, timeout, no_retry, loaded)
        emit(
            ctx,
            _answer_payload(answer, "data"),
            lambda: print(json.dumps(answer.data, ensure_ascii=False, indent=2)),
        )
