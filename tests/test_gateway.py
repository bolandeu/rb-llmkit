"""Клиент шлюза 9router на httpx: запрос, разбор JSON и SSE, поля ответа, ошибки шлюза."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from conftest import GATEWAY_KEY, GATEWAY_MODEL, GATEWAY_ROUTING, FakeGateway, gateway_body, json_reply
from typer.testing import CliRunner

from llmkit import AllModelsFailed, LlmKit, Task
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()
DATA = Path(__file__).parent / "data"


def kit(fake: FakeGateway, **kwargs) -> LlmKit:
    return LlmKit(routing=GATEWAY_ROUTING, transport=fake.transport, **kwargs)


def recorded(name: str, content_type: str) -> httpx.Response:
    """Записанный ответ шлюза из tests/data."""
    return httpx.Response(200, text=(DATA / name).read_text(encoding="utf-8"), headers={"content-type": content_type})


@pytest.fixture
def cli(monkeypatch):
    """`llm` с фейковым шлюзом вместо настоящего."""

    def run(fake: FakeGateway, *args: str):
        monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(transport=fake.transport, **kwargs))
        return runner.invoke(app, [*args, "--json"])

    return run


# --- запрос -----------------------------------------------------------------------


async def test_request_goes_to_the_gateway_chat_endpoint(gateway):
    fake = gateway(json_reply("ответ"))
    await kit(fake).ask(Task(user="вопрос", system="ты бот"))
    request = fake.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://gateway.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {GATEWAY_KEY}"
    body = json.loads(request.content)
    # Шлюз пишет в журнал только поточные вызовы — stream всегда true.
    assert body["stream"] is True
    assert body["messages"] == [{"role": "system", "content": "ты бот"}, {"role": "user", "content": "вопрос"}]


async def test_model_name_goes_verbatim(gateway):
    fake = gateway(json_reply("ответ"))
    answer = await kit(fake, routing={**GATEWAY_ROUTING, "chain": ["deepseek/deepseek-v4.1-flash-1017"]}).ask(
        Task(user="вопрос")
    )
    assert answer.model == "deepseek/deepseek-v4.1-flash-1017"
    assert fake.models() == ["deepseek/deepseek-v4.1-flash-1017"]


# --- ответ -----------------------------------------------------------------------


async def test_json_body_answer_carries_text_and_gateway_fields(gateway):
    fake = gateway(json_reply("Париж", provider="deepseek", cost=0.000042, prompt_tokens=18, completion_tokens=6))
    answer = await kit(fake).ask(Task(user="Столица Франции?"))
    assert answer.data == "Париж"
    assert answer.source == "llm"
    assert answer.model == "Deep Sec"  # запрошенная строка как есть
    assert answer.served_model == GATEWAY_MODEL
    assert answer.provider == "deepseek"
    assert answer.cost_usd == pytest.approx(0.000042)
    assert (answer.prompt_tokens, answer.completion_tokens) == (18, 6)
    assert len(fake.requests) == 1


async def test_sse_answer_is_assembled_from_the_stream(gateway):
    fake = gateway(recorded("gateway_combo.sse", "text/event-stream"))
    answer = await kit(fake).ask(Task(user="Столица Франции?"))
    assert answer.data == "Столица Франции — Париж."
    assert answer.served_model == "deepseek/deepseek-v4.1-flash-1017"
    assert answer.provider == "deepseek"
    assert answer.cost_usd == pytest.approx(0.000042)
    assert (answer.prompt_tokens, answer.completion_tokens) == (18, 6)


async def test_an_answer_without_provider_and_with_zero_cost_is_valid(gateway):
    fake = gateway(recorded("gateway_opencode_go.json", "application/json"))
    answer = await kit(fake).ask(Task(user="собери файл"))
    assert answer.data == "Готово: файл собран."
    assert answer.source == "llm"
    assert answer.provider is None
    assert answer.cost_usd == 0.0


async def test_a_non_streamed_answer_arrives_as_one_sse_line(gateway):
    """Непоточный запрос шлюз тоже отвечает как text/event-stream: одна JSON-строка и [DONE]."""
    text = "data: " + json.dumps(gateway_body("готово", provider="deepseek", cost=0.0), ensure_ascii=False)
    fake = gateway(
        httpx.Response(200, text=f"{text}\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"})
    )
    answer = await kit(fake).ask(Task(user="вопрос"))
    assert answer.data == "готово" and answer.provider == "deepseek" and answer.cost_usd == 0.0


async def test_generate_returns_the_text_of_the_answer(gateway):
    fake = gateway(recorded("gateway_combo.sse", "text/event-stream"))
    assert await kit(fake).generate("Столица Франции?") == "Столица Франции — Париж."


async def test_ask_many_asks_the_gateway_once_per_task(gateway):
    fake = gateway(json_reply("раз"), json_reply("два"))
    answers = await kit(fake).ask_many([Task(user="раз"), Task(user="два")])
    assert [answer.data for answer in answers] == ["раз", "два"]
    assert len(fake.requests) == 2


# --- CLI -------------------------------------------------------------------------


def test_cli_ask_json_reads_the_gateway_answer(cli, gateway):
    result = cli(gateway(recorded("gateway_combo.sse", "text/event-stream")), "ask", "Столица Франции?")
    result = cli(gateway(recorded("gateway_combo.sse", "text/event-stream")), "ask", "Столица Франции?")
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["ok"] is True
    assert body["text"] == "Столица Франции — Париж."
    assert body["served_model"] == "deepseek/deepseek-v4.1-flash-1017"
    assert body["provider"] == "deepseek"
    assert body["cost_usd"] == pytest.approx(0.000042)


def test_cli_ask_json_shows_a_missing_provider_and_zero_cost_as_they_are(cli, gateway):
    result = cli(gateway(recorded("gateway_opencode_go.json", "application/json")), "ask", "собери файл")
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["provider"] is None
    assert body["cost_usd"] == 0.0


# --- ошибки шлюза -------------------------------------------------------------------


async def test_unreachable_gateway_is_gateway_unavailable(gateway):
    from llmkit import GatewayUnavailable

    fake = gateway(httpx.ConnectError("connection refused"))
    with pytest.raises(GatewayUnavailable) as caught:
        await kit(fake).ask(Task(user="вопрос"))
    assert caught.value.url == "http://gateway.test/v1"


async def test_timeout_is_gateway_unavailable(gateway):
    from llmkit import GatewayUnavailable

    fake = gateway(httpx.ReadTimeout("timed out"))
    with pytest.raises(GatewayUnavailable):
        await kit(fake).ask(Task(user="вопрос"))


def test_cli_names_the_gateway_when_it_is_unreachable(cli, gateway):
    result = cli(gateway(httpx.ConnectError("connection refused")), "ask", "вопрос")
    assert result.exit_code == 5
    error = json.loads(result.stdout)["error"]
    assert "http://gateway.test/v1" in json.dumps(error, ensure_ascii=False)


def test_an_http_error_keeps_the_provider_error_exit_code(cli, gateway):
    result = cli(gateway(httpx.Response(503, json={"error": "нет аккаунта"})), "ask", "вопрос")
    assert result.exit_code == 5


def test_an_empty_answer_is_invalid_output_with_exit_5(cli, gateway):
    result = cli(gateway(json_reply("   ")), "ask", "вопрос")
    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["code"] == "PROVIDER_ERROR"


async def test_an_empty_answer_raises_the_existing_error_kind(gateway):
    fake = gateway(json_reply(""))
    with pytest.raises(AllModelsFailed) as caught:
        await kit(fake).ask(Task(user="вопрос"))
    assert caught.value.error_type == "invalid_output"
