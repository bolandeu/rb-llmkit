"""HTTP-клиент шлюза 9router: один запрос на вызов, разбор JSON и SSE ответа.

Методы семейств (`image`, `speech`, `video`…) — тонкая обёртка над `request`:
путь шлюза и типизированный ответ из `parse`, без разбора форматов провайдера.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..errors import GatewayUnavailable
from . import parse
from .parse import Reply

CHAT_PATH = "/chat/completions"
MODELS_PATH = "/models"
MODELS_INFO_PATH = "/models/info"
GEMINI_MODELS_PATH = "/v1beta/models"
IMAGE_PATH = "/images/generations"
SPEECH_PATH = "/audio/speech"
TRANSCRIPTIONS_PATH = "/audio/transcriptions"
VOICES_PATH = "/audio/voices"
VIDEO_PATH = "/videos"
EMBEDDINGS_PATH = "/embeddings"
SEARCH_PATH = "/search"
FETCH_PATH = "/web/fetch"
RESPONSES_PATH = "/responses"
RESPONSES_COMPACT_PATH = "/responses/compact"
MESSAGES_PATH = "/messages"
COUNT_TOKENS_PATH = "/messages/count_tokens"
SYSTEMONE_PATH = "/systemone"
API_CHAT_PATH = "/api/chat"
V1_SUFFIX = "/v1"
PROBE_TIMEOUT = 5.0


def _bearer(api_key: str | None) -> dict[bytes, bytes]:
    """Заголовок авторизации в байтах UTF-8: ключ в тестах — кириллица, а HTTP-заголовок а�SCII не требует."""
    return {b"authorization": f"Bearer {api_key}".encode()} if api_key else {}


def _json_object(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise GatewayUnavailable(str(response.request.url), "server", f"ответ не разобрался как JSON: {exc}") from exc


def _messages(prompt: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt}]


class GatewayClient:
    """Вызовы шлюза по адресу и ключу из routing.

    `transport` — подмена сети в тестах (`httpx.MockTransport`). Ключ не попадает
    ни в сообщения об ошибках, ни в журнал.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Адрес без `/v1`: эндпоинт Gemini-shaped моделей живёт на /v1beta.
        self.root = self.base_url.removesuffix(V1_SUFFIX)
        self.timeout = timeout
        self._api_key = api_key
        self._transport = transport

    @property
    def headers(self) -> dict[bytes, bytes]:
        return _bearer(self._api_key)

    async def request(self, method: str, path: str, *, root: bool = False, **kwargs: Any) -> httpx.Response:
        """Один запрос к шлюзу; сбой шлюза — `GatewayUnavailable`."""
        url = (self.root if root else self.base_url) + path
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self.timeout) as http:
                response = await http.request(method, url, headers=self.headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise GatewayUnavailable(self.base_url, "timeout", type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise GatewayUnavailable(self.base_url, "server", f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            raise GatewayUnavailable(self.base_url, "server", f"HTTP {response.status_code}: {response.text[:200]}")
        return response

    async def _json(self, method: str, path: str, *, root: bool = False, **kwargs: Any) -> Any:
        return _json_object(await self.request(method, path, root=root, **kwargs))

    # --- чат ----------------------------------------------------------------------

    async def chat(self, body: dict[str, Any]) -> Reply:
        """Отправить запрос и разобрать ответ; сбой шлюза — `GatewayUnavailable`."""
        response = await self.request("POST", CHAT_PATH, json=body)
        try:
            return parse.reply(response)
        except ValueError as exc:
            raise GatewayUnavailable(self.base_url, "server", str(exc)) from exc

    async def responses(self, prompt: str, model: str, *, compact: bool = False) -> Reply:
        """Форма `responses`: ответ — текст `output`; compact — тот же путь со сжатием."""
        path = RESPONSES_COMPACT_PATH if compact else RESPONSES_PATH
        return parse.reply_of(await self._json("POST", path, json={"input": prompt, "model": model}))

    async def messages(self, prompt: str, model: str) -> Reply:
        """Форма `messages` (Anthropic): ответ — блоки `content`."""
        return parse.reply_of(
            await self._json("POST", MESSAGES_PATH, json={"messages": _messages(prompt), "model": model})
        )

    async def count_tokens(self, prompt: str, model: str) -> int:
        """Сколько токенов шлюз насчитал запросу."""
        body = await self._json("POST", COUNT_TOKENS_PATH, json={"messages": _messages(prompt), "model": model})
        return parse.count_of((body if isinstance(body, dict) else {}).get("input_tokens"))

    async def systemone(self, prompt: str, model: str) -> Reply:
        """Форма `systemone` шлюза."""
        return parse.reply_of(
            await self._json("POST", SYSTEMONE_PATH, json={"messages": _messages(prompt), "model": model})
        )

    async def api_chat(self, prompt: str, model: str) -> Reply:
        """Форма `/api/chat` шлюза."""
        return parse.reply_of(
            await self._json("POST", API_CHAT_PATH, json={"messages": _messages(prompt), "model": model})
        )

    # --- картинки и речь ----------------------------------------------------------

    async def image(self, prompt: str, model: str, **fields: Any) -> parse.ImageResult:
        """Сгенерировать картинку: шлюз отвечает ссылкой или base64."""
        body = await self._json("POST", IMAGE_PATH, json={"prompt": prompt, "model": model, **fields})
        return parse.image_of(body)

    async def speech(
        self, text: str, model: str, *, voice: str | None = None, fmt: str | None = None
    ) -> parse.SpeechResult:
        """Озвучить текст: ответ — байты файла, не JSON."""
        body: dict[str, Any] = {"model": model, "input": text}
        if voice:
            body["voice"] = voice
        if fmt:
            body["response_format"] = fmt
        response = await self.request("POST", SPEECH_PATH, json=body)
        return parse.SpeechResult(
            blob=response.content, content_type=response.headers.get("content-type", ""), model=model
        )

    async def transcribe(self, file: str, model: str, *, language: str | None = None) -> parse.TranscriptResult:
        """Расшифровать речь из файла: файл уходит multipart-полем `file`."""
        source = Path(file)
        data = {"model": model, **({"language": language} if language else {})}
        body = await self._json(
            "POST", TRANSCRIPTIONS_PATH, data=data, files={"file": (source.name, source.read_bytes())}
        )
        return parse.transcript_of(body, model)

    async def voices(self) -> list[str]:
        """Голоса шлюза: только их идентификаторы."""
        body = await self._json("GET", VOICES_PATH)
        return [str(item.get("id")) for item in (body or {}).get("data") or [] if isinstance(item, dict)]

    # --- видео --------------------------------------------------------------------

    async def video_generate(self, prompt: str, model: str, **fields: Any) -> parse.VideoResult:
        """Задание видео по описанию."""
        body = await self._json("POST", VIDEO_PATH + "/generations", json={"prompt": prompt, "model": model, **fields})
        return parse.video_of(body)

    async def video_edit(self, video: str, prompt: str, model: str) -> parse.VideoResult:
        """Правка готового видео по описанию."""
        body = await self._json("POST", VIDEO_PATH + "/edits", json={"video": video, "prompt": prompt, "model": model})
        return parse.video_of(body)

    async def video_extend(self, video: str, prompt: str, model: str) -> parse.VideoResult:
        """Продолжение готового видео по описанию."""
        body = await self._json(
            "POST", VIDEO_PATH + "/extensions", json={"video": video, "prompt": prompt, "model": model}
        )
        return parse.video_of(body)

    async def video(self, video_id: str) -> parse.VideoResult:
        """Задание видео по id: состояние и ссылка на файл."""
        return parse.video_of(await self._json("GET", f"{VIDEO_PATH}/{video_id}"))

    # --- эмбеддинги, поиск, страница, модели ---------------------------------------

    async def embeddings(self, text: str, model: str) -> parse.EmbeddingsResult:
        """Векторы текста."""
        return parse.embeddings_of(await self._json("POST", EMBEDDINGS_PATH, json={"input": text, "model": model}))

    async def search(self, query: str, model: str) -> parse.SearchResult:
        """Поиск в интернете через шлюз."""
        return parse.search_of(await self._json("POST", SEARCH_PATH, json={"query": query, "model": model}))

    async def fetch(self, url: str) -> parse.PageResult:
        """Загрузить страницу через шлюз: заголовок и текст."""
        body = await self._json("POST", FETCH_PATH, json={"url": url}) or {}
        return parse.PageResult(
            url=str(body.get("url") or url), title=str(body.get("title") or ""), content=str(body.get("content") or "")
        )

    async def model_list(self) -> list[dict]:
        """Модели шлюза формой OpenAI: список объектов как есть."""
        body = await self._json("GET", MODELS_PATH) or {}
        return [item for item in body.get("data") or [] if isinstance(item, dict)]

    async def model_info(self) -> list[dict]:
        """Модели шлюза с подробностями (провайдер, вид услуги)."""
        body = await self._json("GET", MODELS_INFO_PATH) or {}
        return [item for item in body.get("models") or [] if isinstance(item, dict)]

    async def model(self, model_id: str) -> dict:
        """Одна модель шлюза по id."""
        return await self._json("GET", f"{MODELS_PATH}/{model_id}") or {}

    async def gemini_models(self) -> list[dict]:
        """Модели в форме Gemini (`name`, `displayName`) с `/v1beta/models`."""
        body = await self._json("GET", GEMINI_MODELS_PATH, root=True) or {}
        return [item for item in body.get("models") or [] if isinstance(item, dict)]


def probe(
    base_url: str,
    *,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> str | None:
    """Проверка доступности шлюза для `llm doctor`: None — отвечает, иначе текст ошибки."""
    url = base_url.rstrip("/") + MODELS_PATH
    headers = _bearer(api_key)
    try:
        with httpx.Client(transport=transport, timeout=timeout) as http:
            http.get(url, headers=headers).raise_for_status()
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None
