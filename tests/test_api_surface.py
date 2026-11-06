"""Остальная поверхность шлюза: эмбеддинги, поиск и загрузка страницы, модели, прочие формы чата.

Каждая команда — один эндпоинт шлюза и типизированный результат в `--json`;
сеть подменена `gateway_cli` из conftest.
"""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import gateway_body

EMBEDDING_MODEL = "openai/text-embedding-3-small"
CHAT_MODEL = "openai/gpt-5"


def payload(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# --- эмбеддинги -------------------------------------------------------------------


def test_embeddings_return_vectors_model_and_cost(gateway_cli, gateway):
    reply = {
        "model": EMBEDDING_MODEL,
        "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
        "usage": {"prompt_tokens": 3, "cost": 0.0000001},
    }
    fake = gateway(httpx.Response(200, json=reply))
    body = payload(gateway_cli(fake, "embeddings", "create", "текст", "-m", EMBEDDING_MODEL))
    assert body["embeddings"] == [[0.1, 0.2, 0.3]]
    assert body["model"] == EMBEDDING_MODEL
    assert body["cost"] == pytest.approx(0.0000001)
    assert str(fake.requests[0].url) == "http://gateway.test/v1/embeddings"
    assert fake.bodies()[0]["input"] == "текст"


# --- поиск и загрузка страницы -----------------------------------------------------


def test_web_search_returns_typed_results(gateway_cli, gateway):
    results = [
        {"url": "https://a.test", "title": "A", "snippet": "первый"},
        {"url": "https://b.test", "title": "B", "snippet": "второй"},
    ]
    reply = {"model": "perplexity/sonar", "usage": {"cost": 0.005}, "results": results}
    fake = gateway(httpx.Response(200, json=reply))
    body = payload(gateway_cli(fake, "web", "search", "llmkit", "-m", "perplexity/sonar"))
    assert body["results"] == results
    assert body["model"] == "perplexity/sonar"
    assert body["cost"] == pytest.approx(0.005)
    assert str(fake.requests[0].url) == "http://gateway.test/v1/search"
    assert fake.bodies()[0]["query"] == "llmkit"


def test_web_fetch_returns_the_page(gateway_cli, gateway):
    reply = {"url": "https://a.test", "title": "A", "content": "страница целиком"}
    fake = gateway(httpx.Response(200, json=reply))
    body = payload(gateway_cli(fake, "web", "fetch", "https://a.test"))
    assert body["content"] == "страница целиком" and body["title"] == "A"
    assert str(fake.requests[0].url) == "http://gateway.test/v1/web/fetch"
    assert fake.bodies()[0]["url"] == "https://a.test"


# --- модели -----------------------------------------------------------------------


def test_model_list_returns_the_gateway_models(gateway_cli, gateway):
    models = [{"id": "deepseek/deepseek-v4.1-flash-1017"}, {"id": "Deep Sec"}]
    fake = gateway(httpx.Response(200, json={"object": "list", "data": models}))
    body = payload(gateway_cli(fake, "model", "list"))
    assert body["models"] == models
    assert fake.requests[0].method == "GET"
    assert str(fake.requests[0].url) == "http://gateway.test/v1/models"


def test_model_info_returns_the_gateway_details(gateway_cli, gateway):
    models = [{"id": "deepseek/deepseek-v4.1-flash-1017", "provider": "deepseek", "service_kind": "llm"}]
    fake = gateway(httpx.Response(200, json={"models": models}))
    body = payload(gateway_cli(fake, "model", "info"))
    assert body["models"] == models
    assert str(fake.requests[0].url) == "http://gateway.test/v1/models/info"


def test_model_show_returns_one_model(gateway_cli, gateway):
    model = {"id": "deepseek/deepseek-v4.1-flash-1017", "object": "model", "owned_by": "deepseek"}
    fake = gateway(httpx.Response(200, json=model))
    body = payload(gateway_cli(fake, "model", "show", "deepseek/deepseek-v4.1-flash-1017"))
    assert body["model"] == model
    assert fake.requests[0].method == "GET"
    assert str(fake.requests[0].url) == "http://gateway.test/v1/models/deepseek/deepseek-v4.1-flash-1017"


# --- прочие формы чата -------------------------------------------------------------


def responses_reply() -> dict:
    return {
        "id": "resp_1",
        "model": CHAT_MODEL,
        "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Париж"}]}],
        "usage": {"input_tokens": 3, "output_tokens": 1, "cost": 0.002},
    }


@pytest.mark.parametrize(
    "command", [("chat", "responses"), ("chat", "responses-compact")], ids=["responses", "responses-compact"]
)
def test_responses_shapes_return_the_text(gateway_cli, gateway, command):
    fake = gateway(httpx.Response(200, json=responses_reply()))
    body = payload(gateway_cli(fake, *command, "Столица Франции?", "-m", CHAT_MODEL))
    assert body["text"] == "Париж"
    assert body["model"] == CHAT_MODEL
    assert body["cost"] == pytest.approx(0.002)
    path = "/responses" if command[-1] == "responses" else "/responses/compact"
    assert str(fake.requests[0].url) == "http://gateway.test/v1" + path


def test_messages_shape_returns_the_text(gateway_cli, gateway):
    reply = {
        "id": "msg_1",
        "model": "anthropic/claude-x",
        "content": [{"type": "text", "text": "Париж"}],
        "usage": {"input_tokens": 3, "output_tokens": 1, "cost": 0.003},
    }
    fake = gateway(httpx.Response(200, json=reply))
    body = payload(gateway_cli(fake, "chat", "messages", "Столица Франции?", "-m", "anthropic/claude-x"))
    assert body["text"] == "Париж"
    assert body["model"] == "anthropic/claude-x"
    assert body["cost"] == pytest.approx(0.003)
    assert str(fake.requests[0].url) == "http://gateway.test/v1/messages"


def test_messages_count_tokens_returns_the_count(gateway_cli, gateway):
    fake = gateway(httpx.Response(200, json={"input_tokens": 12}))
    body = payload(gateway_cli(fake, "chat", "count-tokens", "Столица Франции?", "-m", CHAT_MODEL))
    assert body["tokens"] == 12
    assert str(fake.requests[0].url) == "http://gateway.test/v1/messages/count_tokens"
    assert fake.bodies()[0]["model"] == CHAT_MODEL


@pytest.mark.parametrize(
    ("command", "path"),
    [(("chat", "systemone"), "/systemone"), (("chat", "api"), "/api/chat")],
    ids=["systemone", "api"],
)
def test_systemone_and_api_chat_return_the_text(gateway_cli, gateway, command, path):
    fake = gateway(httpx.Response(200, json=gateway_body("готово", provider="deepseek", cost=0.0)))
    body = payload(gateway_cli(fake, *command, "вопрос", "-m", CHAT_MODEL))
    assert body["text"] == "готово"
    assert body["provider"] == "deepseek"
    assert str(fake.requests[0].url) == "http://gateway.test/v1" + path


def test_gemini_shaped_models_are_listed(gateway_cli, gateway):
    models = [{"name": "models/gemini-2.0-flash", "displayName": "Gemini 2.0 Flash"}]
    fake = gateway(httpx.Response(200, json={"models": models}))
    body = payload(gateway_cli(fake, "chat", "gemini-models"))
    assert body["models"] == models
    assert fake.requests[0].method == "GET"
    assert str(fake.requests[0].url) == "http://gateway.test/v1beta/models"


# --- ошибки шлюза -------------------------------------------------------------------


def test_a_gateway_error_keeps_exit_code_five(gateway_cli, gateway):
    result = gateway_cli(gateway(httpx.Response(503, json={"error": "нет аккаунта"})), "model", "list")
    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["code"] == "PROVIDER_ERROR"
