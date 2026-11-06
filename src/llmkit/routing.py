"""Routing v1: провайдер шлюза 9router и модели шлюза — данными, а не конфигом llmkit.

Контракт — `contracts/routing-v1.schema.json` и векторы `routing-v1.vectors.json`
(публичные). Здесь та же проверка плюс правило ADR-0001: routing v1 называет один
протокол — `openai_compatible` (шлюз), а имена моделей идут строками как есть.
Ошибка — `RoutingInvalid` с JSON Pointer поля. Секретов в routing нет: только имя
переменной с ключом шлюза.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import RoutingInvalid

# Протоколы прежних релизов: routing v1 принимает только шлюз, остальные — ошибка с его путём.
PROTOCOLS = ("openai_compatible", "openrouter", "openai", "anthropic", "gemini", "ollama", "chatgpt", "claude_cli")
PROTOCOL: Literal["openai_compatible"] = "openai_compatible"
SUBSCRIPTION_PROTOCOLS = frozenset({"chatgpt", "claude_cli"})

_PROVIDER_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class Provider(BaseModel):
    """Провайдер routing: адрес шлюза и имя переменной окружения с его ключом."""

    model_config = ConfigDict(extra="forbid")

    protocol: Literal[
        "openrouter", "openai", "anthropic", "gemini", "ollama", "openai_compatible", "chatgpt", "claude_cli"
    ]
    base_url: str | None = Field(default=None, min_length=1)
    key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class Routing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    providers: dict[str, Provider] = Field(min_length=1)
    # Модели шлюза строками как в его настройке (комбо — одна строка). Порядок и
    # фолбэк исполняет шлюз: llmkit просит первую.
    chain: list[str] | None = Field(default=None, min_length=1)

    def provider(self, name: str) -> Provider:
        try:
            return self.providers[name]
        except KeyError:
            known = ", ".join(sorted(self.providers))
            raise RoutingInvalid("/providers", f"провайдер {name!r} не описан; описаны: {known}") from None

    def with_chain(self, chain: list[str]) -> Routing:
        """Цепочка из CLI (`-m ...`) для routing без своей цепочки."""
        if self.chain:
            raise RoutingInvalid("/chain", "chain задана дважды: и в routing, и через -m — оставьте одно")
        return parse({**self.model_dump(exclude_none=True), "chain": chain})


def _pointer(loc: tuple[Any, ...]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in loc)


def _from_pydantic(exc: ValidationError) -> RoutingInvalid:
    error = exc.errors()[0]
    loc = tuple(part for part in error["loc"] if part != "[key]")
    message = error["msg"]
    if error["type"] == "extra_forbidden":
        name = loc[-1] if loc else ""
        message = f"неизвестное поле {name!r} (в routing v1 его нет)"
    elif error["type"] == "literal_error" and loc and loc[-1] == "protocol":
        message = f"неизвестный protocol {error.get('input')!r}; известные: {', '.join(PROTOCOLS)}"
    return RoutingInvalid(_pointer(loc), message)


def parse(data: Any, *, require_chain: bool = True) -> Routing:
    """Проверить routing v1 → `Routing`; `require_chain=False` — файл провайдеров без цепочки."""
    if isinstance(data, Routing):
        data = data.model_dump(exclude_none=True)
    if not isinstance(data, dict):
        raise RoutingInvalid("", "routing должен быть JSON-объектом")
    try:
        routing = Routing.model_validate(data)
    except ValidationError as exc:
        raise _from_pydantic(exc) from None
    for name, provider in routing.providers.items():
        if not _PROVIDER_NAME.match(name):
            raise RoutingInvalid(_pointer(("providers", name)), "имя провайдера: латиница, цифры, _ . -")
        if provider.protocol != PROTOCOL:
            raise RoutingInvalid(
                _pointer(("providers", name, "protocol")),
                f"routing v1 называет только {PROTOCOL} с адресом шлюза, получено {provider.protocol!r}"
                " (провайдеров в llmkit больше нет: ими владеет шлюз)",
            )
        for field in ("base_url", "key_env"):
            if not getattr(provider, field):
                raise RoutingInvalid(_pointer(("providers", name, field)), f"провайдеру шлюза нужен {field}")
    if routing.chain is None:
        if require_chain:
            raise RoutingInvalid("/chain", "нет цепочки моделей: передайте chain в routing или -m в CLI")
    elif any(not model.strip() for model in routing.chain):
        raise RoutingInvalid("/chain", "имя модели в цепочке пустое")
    return routing


def load(spec: str) -> dict[str, Any]:
    """`--routing`: путь к JSON-файлу или сама JSON-строка (не stdin)."""
    text = spec
    try:
        is_file = "\n" not in spec and Path(spec).is_file()
    except OSError:
        is_file = False
    if is_file:
        try:
            text = Path(spec).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RoutingInvalid("", f"файл routing не читается: {exc}") from exc
    elif not spec.lstrip().startswith(("{", "[")):
        raise RoutingInvalid("", f"routing — не JSON и не существующий файл: {spec!r}")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RoutingInvalid("", f"routing не разбирается как JSON: {exc}") from exc
