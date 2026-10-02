"""Routing v1: провайдеры, цепочка моделей и цены — данными, а не конфигом llmkit.

Контракт — `contracts/routing-v1.schema.json` и векторы `routing-v1.vectors.json`
(публичные). Здесь та же проверка плюс то, что JSON Schema не выражает: модели
цепочки и цен ссылаются на описанных провайдеров. Ошибка — `RoutingInvalid` с
JSON Pointer поля. Секретов в routing нет: только имена переменных с ключами.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import RoutingInvalid

PROTOCOLS = ("openrouter", "openai", "anthropic", "gemini", "ollama", "openai_compatible", "chatgpt", "claude_cli")
# Подписки: свой транспорт, вход `llm auth login`, ключ не нужен.
SUBSCRIPTION_PROTOCOLS = frozenset({"chatgpt", "claude_cli"})
NEEDS_BASE_URL = frozenset({"ollama", "openai_compatible"})

_PROVIDER_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_REF = re.compile(r"^[A-Za-z0-9_.-]+/.+$")


class Price(BaseModel):
    """Цена модели в $ за 1M токенов — главнее справочника LiteLLM."""

    model_config = ConfigDict(extra="forbid")

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal[
        "openrouter", "openai", "anthropic", "gemini", "ollama", "openai_compatible", "chatgpt", "claude_cli"
    ]
    base_url: str | None = Field(default=None, min_length=1)
    key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    mode: Literal["TOOLS", "JSON", "JSON_SCHEMA", "MD_JSON"] | None = None

    @property
    def subscription(self) -> bool:
        return self.protocol in SUBSCRIPTION_PROTOCOLS


class Routing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    providers: dict[str, Provider] = Field(min_length=1)
    chain: list[str] | None = Field(default=None, min_length=1)
    prices: dict[str, Price] = Field(default_factory=dict)

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
        hint = " (уровней больше нет: передайте chain)" if loc == ("levels",) else ""
        hint = hint or (" (в routing — только имя переменной: key_env)" if name == "api_key" else "")
        message = f"неизвестное поле {name!r}{hint}"
    elif error["type"] == "literal_error" and loc and loc[-1] == "protocol":
        message = f"неизвестный protocol {error.get('input')!r}; известные: {', '.join(PROTOCOLS)}"
    return RoutingInvalid(_pointer(loc), message)


def _check_ref(ref: Any, path: str, providers: dict[str, Provider]) -> None:
    if not isinstance(ref, str) or not _REF.match(ref):
        raise RoutingInvalid(path, f"модель должна быть вида 'провайдер/модель', получено {ref!r}")
    name = ref.partition("/")[0]
    if name not in providers:
        known = ", ".join(sorted(providers))
        raise RoutingInvalid(path, f"провайдер {name!r} ({ref}) не описан в providers; описаны: {known}")


def parse(data: Any, *, require_chain: bool = True) -> Routing:
    """Проверить routing v1 → `Routing`; `require_chain=False` — файл провайдеров без цепочки."""
    if isinstance(data, Routing):
        data = data.model_dump(exclude_none=True)
    if not isinstance(data, dict):
        raise RoutingInvalid("", "routing должен быть JSON-объектом")
    # Ссылки цепочки проверяем до pydantic: у «gpt-4o» без провайдера путь точнее.
    chain = data.get("chain")
    if isinstance(chain, list):
        for index, ref in enumerate(chain):
            if not isinstance(ref, str) or not _REF.match(ref):
                raise RoutingInvalid(f"/chain/{index}", f"модель должна быть вида 'провайдер/модель', получено {ref!r}")
    try:
        routing = Routing.model_validate(data)
    except ValidationError as exc:
        raise _from_pydantic(exc) from None
    for name, provider in routing.providers.items():
        if not _PROVIDER_NAME.match(name):
            raise RoutingInvalid(_pointer(("providers", name)), "имя провайдера: латиница, цифры, _ . -")
        if provider.protocol in NEEDS_BASE_URL and not provider.base_url:
            raise RoutingInvalid(
                _pointer(("providers", name, "base_url")), f"протоколу {provider.protocol} нужен base_url"
            )
    if routing.chain is None:
        if require_chain:
            raise RoutingInvalid("/chain", "нет цепочки моделей: передайте chain в routing или -m в CLI")
    else:
        for index, ref in enumerate(routing.chain):
            _check_ref(ref, f"/chain/{index}", routing.providers)
    for ref in routing.prices:
        _check_ref(ref, _pointer(("prices", ref)), routing.providers)
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
