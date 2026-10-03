"""Точки входа CLI в ядро: сборка `LlmKit` и разбор общих аргументов."""

import os
import sys
from pathlib import Path

from .. import routing as routing_mod
from ..core import LlmKit
from ..errors import RoutingMissing
from ..routing import Routing
from .output import bad_arguments

ROUTING_FILE_ENV = "LLMKIT_ROUTING_FILE"


def build_kit(**kwargs) -> LlmKit:
    """Единственное место, где CLI создаёт ядро (тесты подменяют его)."""
    return LlmKit(**kwargs)


def default_routing_path() -> Path:
    """Файл routing по умолчанию: `user_config_dir("llmkit")/routing.json` (Mac — ~/Library/Application Support)."""
    import platformdirs

    return Path(platformdirs.user_config_dir("llmkit")) / "routing.json"


def routing_spec(spec: str | None) -> str | None:
    """`--routing` → файл из LLMKIT_ROUTING_FILE → файл по умолчанию, если он есть → None."""
    if spec:
        return spec
    if env := os.environ.get(ROUTING_FILE_ENV):
        return env
    path = default_routing_path()
    if not path.is_file():
        return None
    mode = path.stat().st_mode & 0o777
    if os.name == "posix" and mode & ~0o600:
        print(f"warning: {path} has permissions {mode:o}, wider than 600: chmod 600 {path}", file=sys.stderr)
    return str(path)


def load_routing(spec: str | None, *, require_chain: bool = True) -> Routing:
    """Routing из `routing_spec` (аргумент → env → файл по умолчанию) → иначе RoutingMissing."""
    spec = routing_spec(spec)
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
