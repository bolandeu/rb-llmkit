"""Точки входа CLI в ядро: сборка `LlmKit` и разбор общих аргументов."""

import os
import sys

from .. import routing as routing_mod
from ..core import LlmKit
from ..errors import RoutingMissing
from ..routing import Routing
from .output import bad_arguments

ROUTING_FILE_ENV = "LLMKIT_ROUTING_FILE"


def build_kit(**kwargs) -> LlmKit:
    """Единственное место, где CLI создаёт ядро (тесты подменяют его)."""
    return LlmKit(**kwargs)


def load_routing(spec: str | None, *, require_chain: bool = True) -> Routing:
    """`--routing` (JSON или путь к файлу) → иначе файл из LLMKIT_ROUTING_FILE → иначе RoutingMissing."""
    if not spec:
        spec = os.environ.get(ROUTING_FILE_ENV) or None
        if spec is None:
            raise RoutingMissing()
    return routing_mod.parse(routing_mod.load(spec), require_chain=require_chain)


def call_routing(spec: str | None, models: list[str] | None) -> Routing:
    """Routing команды вызова модели: цепочка — из routing или из повторяемого `-m`, но не из обоих."""
    if not models:
        return load_routing(spec)
    return load_routing(spec, require_chain=False).with_chain(list(models))


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
