"""Ответ шлюза: JSON или поток SSE, формы чата и типизированные результаты остальных семейств."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

SSE_CONTENT_TYPE = "text/event-stream"


@dataclass(frozen=True)
class Reply:
    """Разобранный ответ шлюза: текст, кто ответил и сколько это стоило."""

    text: str
    served_model: str = ""
    provider: str | None = None
    cost_usd: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None


@dataclass(frozen=True)
class ImageResult:
    """Картинка: ссылка шлюза или байты base64 (их место — файл), модель и цена."""

    url: str | None = None
    blob: bytes | None = None
    model: str = ""
    cost: float | None = None


@dataclass(frozen=True)
class SpeechResult:
    """Речь: байты ответа, их content-type и модель."""

    blob: bytes = b""
    content_type: str = ""
    model: str = ""


@dataclass(frozen=True)
class TranscriptResult:
    """Расшифровка речи: текст, модель и цена."""

    text: str = ""
    model: str = ""
    cost: float | None = None


@dataclass(frozen=True)
class VideoResult:
    """Задание видео шлюза: id, состояние, ссылка на файл, модель и цена."""

    id: str = ""
    status: str = ""
    url: str | None = None
    model: str = ""
    cost: float | None = None


@dataclass(frozen=True)
class EmbeddingsResult:
    """Векторы эмбеддингов, модель и цена."""

    embeddings: list[list[float]] = field(default_factory=list)
    model: str = ""
    cost: float | None = None


@dataclass(frozen=True)
class SearchHit:
    """Один результат поиска шлюза."""

    url: str = ""
    title: str = ""
    snippet: str = ""


@dataclass(frozen=True)
class SearchResult:
    """Результаты поиска, модель и цена."""

    results: list[SearchHit] = field(default_factory=list)
    model: str = ""
    cost: float | None = None


@dataclass(frozen=True)
class PageResult:
    """Загруженная шлюзом страница: адрес, заголовок и текст."""

    url: str = ""
    title: str = ""
    content: str = ""


def reply(response: httpx.Response) -> Reply:
    """Ответ шлюза по content-type: непоточный запрос тоже приходит как text/event-stream."""
    content_type = response.headers.get("content-type", "")
    if SSE_CONTENT_TYPE in content_type:
        from . import sse

        return reply_of(sse.completion(response.text))
    try:
        return reply_of(response.json())
    except ValueError as exc:
        raise ValueError(f"ответ шлюза не разобрался как JSON: {exc}") from exc


def reply_of(body: Any) -> Reply:
    """Форма chat.completion, responses или messages → `Reply`. Нет provider или cost 0 — это норма."""
    if not isinstance(body, dict):
        raise ValueError("ответ шлюза — не JSON-объект")
    usage = body.get("usage") or {}
    return Reply(
        text=text_of(body),
        served_model=str(body.get("model") or ""),
        provider=body.get("provider"),
        cost_usd=_cost(usage.get("cost")),
        prompt_tokens=count_of(usage.get("prompt_tokens") or usage.get("input_tokens")),
        completion_tokens=count_of(usage.get("completion_tokens") or usage.get("output_tokens")),
        finish_reason=_finish_reason(body),
    )


def text_of(body: Any) -> str:
    """Текст ответа в любой форме шлюза: chat.completion, responses или messages."""
    if not isinstance(body, dict):
        return ""
    choice = _first(body.get("choices"))
    content = (choice.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    blocks = [*_list(body.get("output")), *_list(body.get("content"))]
    return "".join(part for block in blocks for part in _texts(block))


def image_of(body: Any) -> ImageResult:
    """Ответ `/images/generations`: первый элемент `data` — ссылка или base64."""
    body = body if isinstance(body, dict) else {}
    first = _first(body.get("data"))
    encoded = first.get("b64_json")
    return ImageResult(
        url=first.get("url"),
        blob=base64.b64decode(encoded) if isinstance(encoded, str) else None,
        model=str(body.get("model") or ""),
        cost=_usage_cost(body),
    )


def transcript_of(body: Any, model: str) -> TranscriptResult:
    """Ответ `/audio/transcriptions`: текст, модель (шлюзовая, если названа) и цена."""
    body = body if isinstance(body, dict) else {}
    return TranscriptResult(
        text=str(body.get("text") or ""), model=str(body.get("model") or model), cost=_usage_cost(body)
    )


def video_of(body: Any) -> VideoResult:
    """Ответ `/videos/*`: id задания, состояние, ссылка на файл, модель и цена."""
    body = body if isinstance(body, dict) else {}
    return VideoResult(
        id=str(body.get("id") or ""),
        status=str(body.get("status") or ""),
        url=body.get("url"),
        model=str(body.get("model") or ""),
        cost=_usage_cost(body),
    )


def embeddings_of(body: Any) -> EmbeddingsResult:
    """Ответ `/embeddings`: векторы по порядку `index`, модель и цена."""
    body = body if isinstance(body, dict) else {}
    items = [item for item in _list(body.get("data")) if isinstance(item, dict)]
    vectors = [list(item.get("embedding") or []) for item in sorted(items, key=lambda item: item.get("index") or 0)]
    return EmbeddingsResult(embeddings=vectors, model=str(body.get("model") or ""), cost=_usage_cost(body))


def search_of(body: Any) -> SearchResult:
    """Ответ `/search`: ссылка, заголовок и сниппет каждого результата, модель и цена."""
    body = body if isinstance(body, dict) else {}
    hits = [
        SearchHit(
            title=str(hit.get("title") or ""), url=str(hit.get("url") or ""), snippet=str(hit.get("snippet") or "")
        )
        for hit in _list(body.get("results"))
        if isinstance(hit, dict)
    ]
    return SearchResult(results=hits, model=str(body.get("model") or ""), cost=_usage_cost(body))


def _first(items: Any) -> dict:
    first = _list(items)[:1] or [{}]
    return first[0] if isinstance(first[0], dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _texts(entry: Any) -> Iterator[str]:
    """Текст одного блока ответа: сам блок или его части `content`."""
    if not isinstance(entry, dict):
        return
    if isinstance(entry.get("text"), str):
        yield entry["text"]
    for block in _list(entry.get("content")):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            yield block["text"]


def _finish_reason(body: dict) -> str | None:
    return _first(body.get("choices")).get("finish_reason")


def _usage_cost(body: dict) -> float | None:
    return _cost((body.get("usage") or {}).get("cost"))


def count_of(value: Any) -> int:
    """Токены из ответа: не число — считаем нулём, ответ из-за этого не теряется."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cost(value: Any) -> float | None:
    """`usage.cost` шлюза: нет поля — цены нет (не ошибка), 0 — ответил подписочный провайдер."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def chunks(text: str) -> list[dict]:
    """Строки SSE (`data: {...}`) без `data: [DONE]` и без мусора."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            found.append(json.loads(payload))
        except ValueError:
            continue
    return found
