"""Общие детали команд поверхности шлюза: клиент из routing, конверт и файл ответа."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from .. import _sync
from ..gateway import GatewayClient
from ..gateway.parse import Reply
from . import runtime
from .output import bad_arguments, out

RoutingOption = typer.Option(
    None, "--routing", help="Routing v1: JSON или файл; иначе LLMKIT_ROUTING_FILE, иначе файл по умолчанию."
)
ModelOption = typer.Option(..., "--model", "-m", help="Модель шлюза строкой как в его настройке.")
OutOption = typer.Option(None, "--out", help="Файл для ответа: картинка или речь приходят байтами.")


def client(routing: str | None) -> GatewayClient:
    """Клиент шлюза: адрес и ключ провайдера из routing."""
    return runtime.build_gateway(routing)


def run(promise):
    """Ответ шлюза в синхронной команде."""
    return _sync.run(promise)


def payload(result: Any) -> dict:
    """Поля типизированного ответа для конверта: сырые байты остаются файлу."""
    return {name: value for name, value in dataclasses.asdict(result).items() if name != "blob"}


def answer_payload(reply: Reply) -> dict:
    """Ответ формы чата для конверта: текст, модель, провайдер и цена."""
    return {"text": reply.text, "model": reply.served_model, "provider": reply.provider, "cost": reply.cost_usd}


def written(path: str | None, data: bytes | None) -> str | None:
    """Записать байты ответа в файл; некуда писать — ошибка аргументов."""
    if data is None:
        return None
    if path is None:
        raise bad_arguments("шлюз ответил файлом", "укажите --out: путь для файла")
    Path(path).write_bytes(data)
    return path


def _flat(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("url") or item.get("title") or item)
    return str(item)


def human(data: dict) -> Callable[[], None]:
    """Человеческий вывод: по строке `поле: значение`, списки — через запятую."""

    def show() -> None:
        for name, value in data.items():
            if value is None:
                continue
            if isinstance(value, list):
                value = ", ".join(_flat(item) for item in value)
            out.print(f"{name}: {value}", highlight=False)

    return show
