"""Точки входа CLI в ядро: сборка `LlmKit` и разбор общих аргументов."""

import sys

from ..core import LlmKit
from .output import bad_arguments


def build_kit(**kwargs) -> LlmKit:
    """Единственное место, где CLI создаёт ядро (тесты подменяют его)."""
    return LlmKit(**kwargs)


def parse_tags(values: list[str] | None) -> dict[str, str]:
    """`--tag tool=intentree` → `{"tool": "intentree"}`."""
    tags: dict[str, str] = {}
    for item in values or []:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise bad_arguments(f"метка должна быть вида k=v, получено {item!r}")
        tags[name] = value
    return tags


def read_text(text: str | None) -> str:
    """Текст запроса: аргумент или stdin, если аргумента нет и это не терминал."""
    if text:
        return text
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            return piped
    raise bad_arguments("нечего спрашивать", "передайте текст аргументом или через stdin")
