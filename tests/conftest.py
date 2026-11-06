"""Общие фикстуры: routing и каталоги пользователя — во временных, сети нет."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

# Typer читает эти переменные один раз при импорте и после этого форсирует терминальный вывод — как на CI.
CI_ENV = {"GITHUB_ACTIONS": "true", "FORCE_COLOR": "1", "PY_COLORS": "1"}

# Routing эпохи шлюза: один openai_compatible провайдер, имена моделей — как в настройке 9router.
GATEWAY_ROUTING: dict = {
    "providers": {
        "9router": {
            "protocol": "openai_compatible",
            "base_url": "http://gateway.test/v1",
            "key_env": "NINEROUTER_API_KEY",
        }
    },
    "chain": ["Deep Sec", "opencode-go"],
}
GATEWAY_KEY = "ключ-шлюза"
GATEWAY_MODEL = "deepseek/deepseek-v4.1-flash-1017"


def gateway_body(
    text: str = "ответ",
    *,
    model: str = GATEWAY_MODEL,
    provider: str | None = None,
    cost: float | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict:
    """Тело ответа шлюза в форме chat.completion; provider и usage.cost шлюз отдаёт не всегда."""
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if cost is not None:
        usage["cost"] = cost
    body: dict[str, Any] = {
        "id": "chatcmpl-9router",
        "object": "chat.completion",
        "created": 1750000000,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": usage,
    }
    if provider is not None:
        body["provider"] = provider
    return body


def json_reply(text: str = "ответ", **fields: Any) -> httpx.Response:
    """Ответ шлюза одним JSON-телом."""
    return httpx.Response(200, json=gateway_body(text, **fields))


def sse_reply(
    text: str = "ответ", *, model: str = GATEWAY_MODEL, provider: str | None = None, cost: float | None = None
) -> httpx.Response:
    """Ответ шлюза потоком text/event-stream: две порции текста и data: [DONE]."""
    head = {"model": model, **({"provider": provider} if provider is not None else {})}
    chunks = [
        {**head, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
        {
            **head,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, **({"cost": cost} if cost is not None else {})},
        },
    ]
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}" for chunk in chunks] + ["data: [DONE]"]
    return httpx.Response(200, text="\n\n".join(lines) + "\n\n", headers={"content-type": "text/event-stream"})


class FakeGateway:
    """Фейковый шлюз 9router: httpx-транспорт пишет запросы и отдаёт заготовленные ответы.

    Элемент сценария — готовый `httpx.Response`, исключение (будет брошено) или
    функция от запроса. Последний элемент повторяется, когда сценарий исчерпан.
    """

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies) or [json_reply()]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply: Any = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            reply = reply(request)
        return reply

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]

    def models(self) -> list[str]:
        return [body["model"] for body in self.bodies()]


@pytest.fixture
def gateway(monkeypatch):
    """Фейковый шлюз с ключом в окружении: `gateway(*ответов)` задаёт сценарий."""
    monkeypatch.setenv("NINEROUTER_API_KEY", GATEWAY_KEY)

    def make(*replies: Any) -> FakeGateway:
        return FakeGateway(*replies)

    return make


@pytest.fixture
def gateway_cli(tmp_path, monkeypatch):
    """`llm` с фейковым шлюзом для команд поверхности: image, audio, video и остальные.

    Собирает клиент шлюза на фейковом транспорте и подменяет им единственную
    точку, где CLI строит клиент (`runtime.build_gateway`).
    """
    from typer.testing import CliRunner

    from llmkit.cli import runtime
    from llmkit.cli.main import app
    from llmkit.gateway import GatewayClient

    path = tmp_path / "routing.json"
    path.write_text(json.dumps(GATEWAY_ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))

    def run(fake: FakeGateway, *args: str):
        client = GatewayClient(base_url="http://gateway.test/v1", api_key=GATEWAY_KEY, transport=fake.transport)
        monkeypatch.setattr(runtime, "build_gateway", lambda *a, **kw: client, raising=False)
        return CliRunner().invoke(app, [*args, "--json"])

    return run


@pytest.fixture
def gateway_server():
    """Настоящий локальный HTTP-сервер вместо шлюза: отвечает 200 на любой запрос."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            body = b'{"data": []}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _reply
        do_POST = _reply

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _plain_terminal(monkeypatch):
    """Справка без цвета и с фиксированной шириной, как бы ни был настроен CI: Typer форсирует терминал при импорте."""
    import typer.rich_utils

    from llmkit.cli import output

    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", False)
    # Консоли llmkit создаются при импорте и тоже читают FORCE_COLOR.
    for console in (output.out, output.err):
        monkeypatch.setattr(console, "_force_terminal", False)
        monkeypatch.setattr(console, "_color_system", None)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Каталоги пользователя — временные, routing — только явно, ключей машины нет."""
    monkeypatch.delenv("LLMKIT_ROUTING_FILE", raising=False)
    monkeypatch.delenv("LLMKIT_GATEWAY_DB", raising=False)
    # Файл routing по умолчанию — в каталоге конфигурации пользователя; настоящий не должен влиять.
    import platformdirs

    monkeypatch.setattr(
        platformdirs, "user_config_dir", lambda appname=None, *a, **k: str(tmp_path / "user-config" / appname)
    )
    for name in list(os.environ):  # ключи машины не должны влиять на тесты
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name)
    monkeypatch.delenv("LLMKIT_LOG_LEVEL", raising=False)
    return tmp_path


@pytest.fixture
def contract_offline(monkeypatch):
    """Офлайн-шлюз для контрактов потребителей (tests/contracts/fixtures.yaml).

    Routing фикстур описывает провайдера `contract`; сеть подменена: модели
    contract/broken* падают с 503, на запрос по схеме шлюз отвечает
    JSON {verdict, remarks}, иначе — текстом. Ключ — фейковый.
    """
    from llmkit import LlmKit
    from llmkit.cli import runtime

    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"].startswith("contract/broken"):
            return httpx.Response(503, json={"error": "contract fixture"})
        if "response_format" in body:
            return json_reply('{"verdict": "ok", "remarks": []}')
        return json_reply("ответ офлайн-провайдера")

    fake = FakeGateway(reply)
    monkeypatch.setenv("LLM_CONTRACT_API_KEY", "contract-fake-key")
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(transport=fake.transport, **kwargs))
    return fake


@pytest.fixture
def same_in_ci(request: pytest.FixtureRequest) -> Callable[[str], None]:
    """Перезапускает тесты этого файла по `-k` под CI_ENV в новом интерпретаторе: значение читается при импорте."""
    if request.config.getoption("--snapshot-update"):
        pytest.skip("снимки пишутся: сравнивать ещё не с чем")

    def run(selection: str) -> None:
        options = ["-k", selection, "-p", "no:cacheprovider", "--no-cov", "-q"]
        command = [sys.executable, "-m", "pytest", str(request.path), *options]
        env = {**os.environ, **CI_ENV}
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        assert result.returncode == 0, result.stdout[-3000:]

    return run
