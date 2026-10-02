"""Команда `llm render` и `--template/--vars` команд вызова модели."""

import hashlib
import json
import re
import sys
from pathlib import Path

import typer

from ..template import render as render_template
from .app import app
from .output import JsonOption, bad_arguments, emit, enable_json, guard

TemplateOption = typer.Option(
    None, "--template", "-t", help="Шаблон mustache: файл, сам текст или '-' (stdin); заменяет текст запроса."
)
VarsOption = typer.Option(None, "--vars", help="Переменные шаблона: JSON-файл или JSON-строка с объектом.")
LenientOption = typer.Option(
    False, "--lenient", help="Отсутствующая переменная — пустая строка, а не ошибка (для отладки)."
)

# Похоже на путь, а не на текст промпта: без пробелов, с каталогом или расширением.
_PATH_LIKE = re.compile(r"^\S*(/\S*|\.[A-Za-z0-9]{1,10})$")


def _is_file(value: str) -> bool:
    try:
        return "\n" not in value and Path(value).is_file()
    except OSError:  # слишком длинное имя и т.п. — это текст
        return False


def _read_template(spec: str) -> tuple[str, str, bytes]:
    """`--template` → (текст, имя для учёта, байты для хэша)."""
    if spec == "-":
        text = sys.stdin.read()
        return text, "stdin", text.encode()
    if _is_file(spec):
        path = Path(spec)
        raw = path.read_bytes()
        try:
            return raw.decode("utf-8"), path.name, raw
        except UnicodeDecodeError as exc:
            raise bad_arguments(f"шаблон {spec} не в UTF-8: {exc}") from exc
    if "{{" not in spec and _PATH_LIKE.match(spec):
        raise bad_arguments(f"файл шаблона не найден: {spec}", "передайте путь к файлу, текст шаблона или '-'")
    return spec, "inline", spec.encode()


def _read_vars(spec: str | None) -> dict:
    if spec is None:
        return {}
    text = spec
    if _is_file(spec):
        try:
            text = Path(spec).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise bad_arguments(f"переменные не читаются: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise bad_arguments(f"переменные не разбираются как JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise bad_arguments("переменные должны быть JSON-объектом")
    return data


def render_spec(template: str, variables: str | None, lenient: bool) -> tuple[str, dict[str, str]]:
    """Отрендерить `--template` с `--vars` → (текст, метки учёта: имя и хэш шаблона, без значений)."""
    source, name, raw = _read_template(template)
    text = render_template(source, _read_vars(variables), strict=not lenient)
    return text, {"template": name, "template_sha256": hashlib.sha256(raw).hexdigest()[:12]}


def prompt_text(
    text: str | None, template: str | None, variables: str | None, lenient: bool
) -> tuple[str | None, dict]:
    """Текст запроса команд вызова модели: аргумент/stdin или отрендеренный шаблон + его метки."""
    if template is None:
        if variables is not None or lenient:
            raise bad_arguments("--vars и --lenient работают только с --template")
        return text, {}
    if text:
        raise bad_arguments("нужен либо текст запроса, либо --template, не оба")
    rendered, tags = render_spec(template, variables, lenient)
    if not rendered.strip():
        raise bad_arguments("шаблон отрендерился в пустой текст")
    return rendered.strip(), tags


@app.command("render")
def render(
    ctx: typer.Context,
    template: str = TemplateOption,
    variables: str = VarsOption,
    lenient: bool = LenientOption,
    json_output: bool = JsonOption,
) -> None:
    """Отрендерить шаблон промпта mustache и напечатать текст.

    Экранирования HTML нет: `{{x}}` == `{{{x}}}`. Отсутствующая переменная —
    ошибка с её именем (`--lenient` — пустая строка). Тот же `--template/--vars`
    есть у `llm ask`, `llm json` и `llm decide`. В режиме `--json` — конверт
    с полем `text`. Коды выхода: 0 — готово, 2 — нет шаблона, битый JSON
    переменных, ошибка шаблона или нет переменной.

    Example: llm render --template prompt.md --vars '{"city": "Москва"}'
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        if template is None:
            raise bad_arguments("нет шаблона", "передайте --template <файл|текст|->")
        text, _ = render_spec(template, variables, lenient)
        emit(ctx, {"text": text}, lambda: print(text, end=""))
