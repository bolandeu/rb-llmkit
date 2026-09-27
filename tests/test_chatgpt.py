"""Подписка ChatGPT: токены, обновление, транспорт Responses API — без сети."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import stat
import time

import httpx
import pytest

from llmkit.errors import LoginMissing
from llmkit.transports import _common, chatgpt, chatgpt_auth
from llmkit.transports.chatgpt_auth import Auth


def jwt(claims: dict) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


def id_token(account: str | None = "acc_1", plan: str = "pro") -> str:
    claim = {"chatgpt_account_id": account, "chatgpt_plan_type": plan} if account else {}
    return jwt({"https://api.openai.com/auth": claim})


def access(expires_in: float, tag: str = "a") -> str:
    return jwt({"exp": int(time.time() + expires_in), "tag": tag})


@pytest.fixture
def auth_file(tmp_path):
    return tmp_path / "chatgpt-auth.json"


def login(path, *, expires_in: float = 3600, tag: str = "a") -> Auth:
    auth = Auth(access_token=access(expires_in, tag), refresh_token="r1", id_token=id_token(), account_id="acc_1")
    chatgpt_auth.write_auth(auth, path)
    return auth


# --- токены ---


def test_account_and_plan_from_id_token():
    assert chatgpt_auth.account_from_id_token(id_token()) == ("acc_1", "pro")
    assert chatgpt_auth.account_from_id_token("мусор") == (None, None)


def test_merge_keeps_account_when_new_id_token_has_none():
    prev = Auth(access_token="old", refresh_token="r1", id_token=id_token(), account_id="acc_1", plan_type="pro")
    merged = chatgpt_auth.merge_tokens({"access_token": "new", "id_token": id_token(account=None)}, prev)
    assert (merged.access_token, merged.refresh_token, merged.account_id, merged.plan_type) == (
        "new", "r1", "acc_1", "pro",
    )  # fmt: skip


def test_write_auth_is_private(auth_file):
    login(auth_file)
    assert stat.S_IMODE(auth_file.stat().st_mode) == 0o600
    auth = chatgpt_auth.read_auth(auth_file)
    assert auth is not None and auth.account_id == "acc_1"


def test_pkce_challenge_is_sha256_of_verifier():
    verifier, challenge = chatgpt_auth.pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


class TokenServer:
    """Токен-эндпоинт OpenAI: отвечает по сценарию и считает обращения."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return self.responses[min(self.calls, len(self.responses)) - 1]


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fresh_token_is_not_refreshed(auth_file):
    auth = login(auth_file)
    server = TokenServer(httpx.Response(500))
    async with client_for(server) as client:
        got = await chatgpt_auth.TokenStore(auth_file).access(client)
    assert got.access_token == auth.access_token and server.calls == 0


async def test_expired_token_is_refreshed_once_for_concurrent_calls(auth_file):
    login(auth_file, expires_in=-10)
    fresh = access(3600, "fresh")
    server = TokenServer(httpx.Response(200, json={"access_token": fresh, "refresh_token": "r2"}))
    store = chatgpt_auth.TokenStore(auth_file)
    async with client_for(server) as client:
        results = await asyncio.gather(*(store.access(client) for _ in range(5)))
    assert server.calls == 1
    assert {r.access_token for r in results} == {fresh}
    saved = chatgpt_auth.read_auth(auth_file)
    assert saved is not None
    assert (saved.access_token, saved.refresh_token, saved.account_id) == (fresh, "r2", "acc_1")


async def test_refresh_without_access_token_keeps_login(auth_file):
    before = login(auth_file, expires_in=-10)
    server = TokenServer(httpx.Response(200, json={"access_token": ""}))
    async with client_for(server) as client:
        with pytest.raises(_common.SubscriptionAuthError):
            await chatgpt_auth.TokenStore(auth_file).access(client)
    assert chatgpt_auth.read_auth(auth_file) == before


async def test_failed_refresh_adopts_token_written_by_other_process(auth_file):
    login(auth_file, expires_in=-10)
    fresh = access(3600, "other")

    def handler(request):
        # Пока мы обновлялись, соседний процесс уже записал новый токен.
        login(auth_file, tag="other")
        return httpx.Response(400, json={"error": "refresh_token_reused"})

    async with client_for(handler) as client:
        got = await chatgpt_auth.TokenStore(auth_file).access(client)
    saved = chatgpt_auth.read_auth(auth_file)
    assert saved is not None and got.access_token == saved.access_token
    assert chatgpt_auth.parse_jwt(got.access_token)["tag"] == chatgpt_auth.parse_jwt(fresh)["tag"]


async def test_no_login_raises_login_missing(auth_file):
    async with client_for(TokenServer(httpx.Response(500))) as client:
        with pytest.raises(LoginMissing, match="llm auth login gpt"):
            await chatgpt_auth.TokenStore(auth_file, "gpt").access(client)


# --- транспорт ---


def test_body_moves_system_to_instructions_and_disables_strict():
    body = chatgpt.build_body(
        "gpt-5.5",
        [
            {"role": "system", "content": "будь краток"},
            {"role": "user", "content": "привет"},
            {"role": "assistant", "content": "здравствуйте"},
            {"role": "user", "content": [{"type": "text", "text": "ещё"}]},
        ],
        {"type": "json_schema", "json_schema": {"name": "X", "schema": {"type": "object"}, "strict": True}},
    )
    assert body["instructions"] == "будь краток"
    assert body["store"] is False and body["stream"] is True
    assert [item["role"] for item in body["input"]] == ["user", "assistant", "user"]
    assert body["input"][1]["content"][0]["type"] == "output_text"
    assert body["text"]["format"] == {"type": "json_schema", "name": "X", "schema": {"type": "object"}, "strict": False}
    assert "temperature" not in body and "max_output_tokens" not in body


def sse(*events: dict) -> str:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


COMPLETED = {
    "type": "response.completed",
    "response": {"status": "completed", "usage": {"input_tokens": 12, "output_tokens": 3}, "output": []},
}


class Backend:
    """Бэкенд Codex: записывает запросы, отвечает по сценарию."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": access(3600, "forced"), "refresh_token": "r2"})
        self.requests.append(request)
        return self.responses[min(len(self.requests), len(self.responses)) - 1]


@pytest.fixture
def backend(monkeypatch):
    def install(*responses):
        server = Backend(*responses)
        monkeypatch.setattr(chatgpt, "_client_factory", lambda timeout: client_for(server))
        return server

    return install


async def call(auth_file, **kwargs):
    return await chatgpt.acompletion(
        model="gpt-5.5", messages=[{"role": "user", "content": "hi"}], auth_file=str(auth_file), **kwargs
    )


async def test_completion_collects_stream(auth_file, backend):
    login(auth_file)
    server = backend(
        httpx.Response(200, text=sse({"type": "response.output_text.delta", "delta": "по"},
                                     {"type": "response.output_text.delta", "delta": "нг"}, COMPLETED))
    )  # fmt: skip
    response = await call(auth_file)
    assert response.choices[0].message.content == "понг"
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (12, 3)
    headers = server.requests[0].headers
    assert headers["chatgpt-account-id"] == "acc_1" and headers["originator"] == "codex_cli_rs"


async def test_rejected_token_is_force_refreshed_and_retried_once(auth_file, backend):
    login(auth_file)
    server = backend(
        httpx.Response(401, json={"error": {"code": "token_expired"}}),
        httpx.Response(200, text=sse({"type": "response.output_text.delta", "delta": "ok"}, COMPLETED)),
    )
    response = await call(auth_file)
    assert response.choices[0].message.content == "ok"
    retried = server.requests[1].headers["authorization"]
    assert chatgpt_auth.parse_jwt(retried.split()[1])["tag"] == "forced"


async def test_rate_limit_keeps_retry_after(auth_file, backend):
    login(auth_file)
    backend(httpx.Response(429, headers={"retry-after": "7"}, text="slow down"))
    with pytest.raises(_common.SubscriptionRateLimit) as info:
        await call(auth_file)
    from llmkit import chain

    assert chain.classify(info.value) == "rate_limit" and chain.retry_after(info.value) == 7.0


async def test_stream_error_event_is_classified(auth_file, backend):
    login(auth_file)
    backend(httpx.Response(200, text=sse({"type": "response.failed", "response": {
        "error": {"code": "usage_limit_reached", "message": "limit"}}})))  # fmt: skip
    with pytest.raises(_common.SubscriptionRateLimit):
        await call(auth_file)
