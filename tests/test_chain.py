"""Один вызов — один запрос к шлюзу: своей цепочки, фолбэка и ретраев у llmkit нет."""

from __future__ import annotations

import httpx
import pytest
from conftest import GATEWAY_ROUTING, FakeGateway, json_reply

from rb_llmkit import LlmKit, Task


def kit(fake: FakeGateway) -> LlmKit:
    return LlmKit(routing=GATEWAY_ROUTING, transport=fake.transport)


async def test_one_completed_call_sends_exactly_one_request(gateway):
    fake = gateway(json_reply("ответ"))
    answer = await kit(fake).ask(Task(user="вопрос"))
    assert len(fake.requests) == 1
    assert fake.models() == ["Deep Sec"]
    assert len(answer.attempts) == 1


async def test_no_second_model_of_the_chain_is_tried(gateway):
    from rb_llmkit import GatewayUnavailable

    fake = gateway(httpx.Response(503, json={"error": "нет аккаунта"}))
    with pytest.raises(GatewayUnavailable):
        await kit(fake).ask(Task(user="вопрос"))
    assert len(fake.requests) == 1
    assert fake.models() == ["Deep Sec"]  # opencode-go не пробовали


async def test_a_server_error_is_not_retried_by_llmkit(gateway):
    from rb_llmkit import GatewayUnavailable

    fake = gateway(httpx.Response(500, json={"error": "сбой шлюза"}))
    with pytest.raises(GatewayUnavailable):
        await kit(fake).ask(Task(user="вопрос"))
    assert len(fake.requests) == 1  # повтор — дело шлюза


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (httpx.ConnectError("нет шлюза"), "server"),
        (httpx.ReadTimeout("долго"), "timeout"),
        (httpx.Response(503, json={}), "server"),
    ],
)
async def test_gateway_failures_keep_the_existing_error_kinds(gateway, failure, kind):
    from rb_llmkit import GatewayUnavailable

    with pytest.raises(GatewayUnavailable) as caught:
        await kit(gateway(failure)).ask(Task(user="вопрос"))
    assert caught.value.kind == kind
