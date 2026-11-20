"""Текст и JSON по схеме через шлюз: ask/generate/ask_many и повтор невалидного ответа."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import GATEWAY_ROUTING, FakeGateway, json_reply
from pydantic import BaseModel

from rb_llmkit import AllModelsFailed, LlmKit, Task


class Shape(BaseModel):
    name: str


def kit(fake: FakeGateway) -> LlmKit:
    return LlmKit(routing=GATEWAY_ROUTING, transport=fake.transport)


async def test_text_answer_is_the_gateway_text(gateway):
    fake = gateway(json_reply("привет"))
    answer = await kit(fake).ask(Task(user="вопрос"))
    assert answer.data == "привет"
    assert answer.source == "llm"
    assert answer.ok and len(fake.requests) == 1


async def test_schema_ask_asks_for_json_by_schema(gateway):
    fake = gateway(json_reply('{"name": "куб"}'))
    answer = await kit(fake).ask(Task(user="как называется фигура?", schema=Shape))
    assert answer.data == Shape(name="куб")
    body = fake.bodies()[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == Shape.model_json_schema()


async def test_invalid_answer_is_retried_with_the_validation_error(gateway):
    fake = gateway(json_reply('{"name": 5}'), json_reply('{"name": 5}'), json_reply('{"name": "куб"}'))
    answer = await kit(fake).ask(Task(user="как называется фигура?", schema=Shape))
    assert answer.data == Shape(name="куб")
    assert len(fake.requests) == 3
    # Повтор несёт текст ошибки валидации, иначе модель повторит тот же ответ.
    retry = json.dumps(fake.bodies()[1]["messages"], ensure_ascii=False)
    assert "Input should be a valid string" in retry


async def test_schema_ask_fails_after_the_last_retry(gateway):
    fake = gateway(json_reply('{"name": 5}'))
    with pytest.raises(AllModelsFailed) as caught:
        await kit(fake).ask(Task(user="как называется фигура?", schema=Shape))
    # Существующий вид ошибки невалидного ответа: CLI переводит его в свой код выхода.
    assert caught.value.error_type == "invalid_output"
    assert len(fake.requests) == 3  # исходный запрос и два повтора (retry.invalid_output = 2)


async def test_generate_returns_the_text(gateway):
    fake = gateway(json_reply("готово"))
    assert await kit(fake).generate("вопрос") == "готово"


async def test_generate_returns_none_when_the_gateway_is_down(gateway):
    fake = gateway(httpx.ConnectError("нет шлюза"))
    assert await kit(fake).generate("вопрос") is None


async def test_ask_many_keeps_the_order_of_the_tasks(gateway):
    fake = gateway(json_reply("раз"), json_reply("два"), json_reply("три"))
    answers = await kit(fake).ask_many([Task(user="раз"), Task(user="два"), Task(user="три")])
    assert [answer.data for answer in answers] == ["раз", "два", "три"]
    assert len(fake.requests) == 3
